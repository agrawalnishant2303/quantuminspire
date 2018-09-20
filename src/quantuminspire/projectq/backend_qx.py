""" Quantum Inspire SDK

This file contains code modified from https://github.com/ProjectQ-Framework/ProjectQ in the QIBackend class.
The ProjectQ code is under the Apache License 2.0.


Copyright 2018 QuTech Delft

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import random

from projectq.cengines import BasicEngine
from projectq.meta import LogicalQubitIDTag, get_control_count
from projectq.ops import (NOT, Allocate, Barrier, Deallocate, FlushGate, H,
                          Measure, Ph, Rx, Ry, Rz, S, Sdag, Swap, T, Tdag, X,
                          Y, Z)

from quantuminspire.exceptions import ProjectQBackendError


class QIBackend(BasicEngine):
    """ Backend for Quantum Inspire

    """

    def __init__(self, num_runs=1024, verbose=0,
                 quantum_inspire_api=None, backend_type=None, nqubits=8,
                 perform_execution=True):
        """
        Initialize the Backend object.

        Args:
            num_runs (int): Number of runs to collect statistics.
                (default is 1024)
            verbose (int): Verbosity level
            quantum_inspire_api (QuantumInspireAPI or None): connection to QI platform
            backend_type (dict or str or None): Backend to use for execution.
            nqubits (int): number of qubits to request to the backend
            perform_execution (bool): If True perform execution, otherwise generate cQASM
        """
        BasicEngine.__init__(self)
        self._reset()
        self._perform_execution = perform_execution
        self._probabilities = dict()
        self._num_runs = num_runs
        self._verbose = verbose
        self._cqasm = str()
        self.quantum_inspire_api = quantum_inspire_api
        self.backend_type = backend_type
        self.nqubits = nqubits

    def cqasm(self):
        """ Return cqasm code that as generated last """
        return self._cqasm

    def is_available(self, cmd):
        """
        Return true if the command can be executed.

        Args:
            cmd (Command): Command for which to check availability
        """
        count = get_control_count(cmd)
        g = cmd.gate
        if self._verbose:
            print('call to is_available with cmd %s (gate %s)' % (cmd, g))
        if g == NOT and count <= 2:
            return True
        if g == Z and count <= 1:
            return True
        if g in (Measure, Allocate, Deallocate, Barrier):
            return True
        if count != 0:
            return False
        if g in (T, Tdag, S, Sdag, H, X, Y, Z):
            return True
        elif isinstance(g, (Rx, Ry, Rz)):
            return True
        elif isinstance(g, Ph):
            return False
        else:
            return False

    def _reset(self):
        """ Reset all temporary variables (after flush gate). """
        self._allocated_qubits = set()
        self._measured_ids = []
        self._max_qubit_id = -1
        self._clear = True
        self.qasm = ""

    def _store(self, cmd):
        """
        Temporarily store the command cmd.

        Translates the command and stores it in a local variable (self._cmds).

        Args:
            cmd: Command to store
        """
        if self._verbose >= 2:
            print('_store {0}: cmd {1}'.format(id(self), cmd))
            print('   _allocated_qubits {0}'.format(self._allocated_qubits))

        if self._clear:
            self._probabilities = dict()
            self._clear = False
            self.qasm = ""
            self._allocated_qubits = set()

        gate = cmd.gate

        self._gate = gate
        if gate == Allocate:
            self._allocated_qubits.add(cmd.qubits[0][0].id)
            self._max_qubit_id = max(self._max_qubit_id, cmd.qubits[0][0].id)
            if self._verbose >= 2:
                print('_store: Allocate gate {0}'.format((cmd.qubits[0][0].id,)))
            return

        if gate == Deallocate:
            if self._verbose >= 2:
                print('_store: Deallocate gate {0}'.format((gate,)))
            index_to_remove = cmd.qubits[0][0].id
            self._allocated_qubits.discard(index_to_remove)
            return

        if gate == Measure:
            assert len(cmd.qubits) == 1 and len(cmd.qubits[0]) == 1
            logical_id = None
            for t in cmd.tags:
                if isinstance(t, LogicalQubitIDTag):
                    logical_id = t.logical_qubit_id
                    break
            assert logical_id is not None
            self._measured_ids += [logical_id]
        elif gate == NOT and get_control_count(cmd) == 1:
            # this case also covers the CX controlled gate
            ctrl_pos = cmd.control_qubits[0].id
            qb_pos = cmd.qubits[0][0].id
            self.qasm += "\nCNOT q[{}], q[{}]".format(ctrl_pos, qb_pos)
        elif gate == Swap:
            q0 = cmd.qubits[0][0].id
            q1 = cmd.qubits[1][0].id
            self.qasm += "\nswap q[{}], q[{}]".format(q0, q1)
        elif gate == X and get_control_count(cmd) == 2:
            ctrl_pos1 = cmd.control_qubits[0].id
            ctrl_pos2 = cmd.control_qubits[1].id
            qb_pos = cmd.qubits[0][0].id
            self.qasm += "\nToffoli q[{}], q[{}], q[{}]".format(ctrl_pos1, ctrl_pos2, qb_pos)
        elif gate == Z and get_control_count(cmd) == 1:
            ctrl_pos = cmd.control_qubits[0].id
            qb_pos = cmd.qubits[0][0].id
            self.qasm += "\nCZ q[{}], q[{}]".format(ctrl_pos, qb_pos)
        elif gate == Barrier:
            qb_pos = [qb.id for qr in cmd.qubits for qb in qr]
            self.qasm += "\n# barrier gate "
            qb_str = ""
            for pos in qb_pos:
                qb_str += "q[{}], ".format(pos)
            self.qasm += qb_str[:-2] + ";"
        elif isinstance(gate, Rz) and get_control_count(cmd) == 1:
            ctrl_pos = cmd.control_qubits[0].id
            qb_pos = cmd.qubits[0][0].id
            gatename = 'CR'
            self.qasm += "\n{} q[{}],q[{}],{:.12f}".format(gatename, ctrl_pos, qb_pos, gate.angle)
        elif isinstance(gate, (Rx, Ry)) and get_control_count(cmd) == 1:
            raise NotImplementedError('controlled Rx or Ry gate not implemented')
        elif isinstance(gate, (Rx, Ry, Rz)):
            assert get_control_count(cmd) == 0
            qb_pos = cmd.qubits[0][0].id
            gatename = str(gate)[0:2]
            self.qasm += "\n{} q[{}],{:.12g}".format(gatename, qb_pos, gate.angle)
        elif gate == Tdag and get_control_count(cmd) == 0:
            qb_pos = cmd.qubits[0][0].id
            self.qasm += "\nTdag q[{}]".format(qb_pos)
        elif isinstance(gate, tuple(type(gate) for gate in (X, Y, Z, H, S, Sdag, T, Tdag))):
            assert get_control_count(cmd) == 0
            if str(gate) in self._gate_names:
                gate_str = self._gate_names[str(gate)]
            else:
                gate_str = str(gate).lower()

            qb_pos = cmd.qubits[0][0].id
            self.qasm += "\n{} q[{}]".format(gate_str, qb_pos)
        else:
            raise NotImplementedError('cmd {0} not implemented'.format((cmd,)))

    def _logical_to_physical(self, qb_id):
        """
        Return the physical location of the qubit with the given logical id.

        Args:
            qb_id (int): ID of the logical qubit whose position should be
                returned.
        """
        assert self.main_engine.mapper is not None
        mapping = self.main_engine.mapper.current_mapping
        if qb_id not in mapping:
            raise RuntimeError("Unknown qubit id {}. Please make sure "
                               "eng.flush() was called and that the qubit "
                               "was eliminated during optimization."
                               .format(qb_id))
        return mapping[qb_id]

    @staticmethod
    def format_histogram(histogram_input, number_of_qubits, number_of_runs=None):
        """ Converts the histogram into the correct format with binary value state items.

        Args:
            histogram_input (dict): The histogram result output of the executed cqasm.
            number_of_qubits (int): The number of qubits.
            number_of_runs (int): The number of runs

        Returns:
            dict: The converted histogram.
        """
        histogram = {}
        for register, value in histogram_input.items():
            byte_value = ("{:0%db}" % number_of_qubits).format(int(register))
            if number_of_runs is not None:
                value = int(number_of_runs * value)
            histogram[byte_value] = value
        return histogram

    def get_probabilities(self, qureg):
        """
        Return the list of basis states with corresponding probabilities.

        The measured bits are ordered according to the supplied quantum
        register, i.e., the left-most bit in the state-string corresponds to
        the first qubit in the supplied quantum register.

        Warning:
            Only call this function after the circuit has been executed!

        Args:
            qureg (list<Qubit>): Quantum register determining the order of the
                qubits.

        Returns:
            probability_dict (dict): Dictionary mapping n-bit strings to
            probabilities.

        Raises:
            RuntimeError: If no data is available (i.e., if the circuit has
                not been executed). Or if a qubit was supplied which was not
                present in the circuit (might have gotten optimized away).
        """
        if len(self._probabilities) == 0:
            raise RuntimeError("Please, run the circuit first!")

        probability_dict = dict()

        for state in self._probabilities:
            mapped_state = ['0'] * len(qureg)
            for i in range(len(qureg)):
                mapped_state[i] = state[self._logical_to_physical(qureg[i].id)]
            probability = self._probabilities[state]
            probability_dict["".join(mapped_state)] = probability

        return probability_dict

    def _calculate_probabilities(self, counts):
        """ Determine probabilities and set single measurement to register """
        # Determine random outcome
        P = random.random()
        p_sum = 0.
        measured = ""
        for state in counts:
            probability = counts[state] * 1. / self._num_runs
            state = list(reversed(state))
            state = "".join(state)
            p_sum += probability
            star = ""
            if p_sum >= P and measured == "":
                measured = state
                star = "*"
            self._probabilities[state] = probability
            if self._verbose and probability > 0:
                print("{0} with p = {1}{2}".format(state, probability, star))
        return measured

    def _run(self):
        """
        Run the circuit.

        Send the circuit via the Quantum Inspire API
        """
        if self.qasm == "":
            return

        if self._verbose:
            print('_run (id {0})'.format((id(self), )))
        # finally: add measurement commands for all measured qubits
        # only measurements after all gate operations will perform properly
        for measured_id in self._measured_ids:
            qb_loc = self.main_engine.mapper.current_mapping[measured_id]
            self.qasm += "\nmeasure q[{}] ".format(qb_loc,)

        if self._verbose >= 2:
            print('_run: self._allocated_qubits {0}'.format((self._allocated_qubits, )))
        max_qubit_id = self._max_qubit_id

        qasm = 'version 1.0\n# generated by Quantum Inspire {0} class\nqubits {1}\n\n'.format(
            self.__class__, max_qubit_id+1)
        qasm += self.qasm

        try:
            if self._verbose:
                print('sending cqasm:')
                print('------')
                print(qasm)
                print('------')
            self._cqasm = qasm

            if self._perform_execution:
                self._quantum_inspire_result = self.quantum_inspire_api.execute_qasm(
                    self._cqasm, backend_type=self.backend_type)
                if len(self._quantum_inspire_result.get('histogram', {})) == 0:
                    raw_text = self._quantum_inspire_result.get('raw_text', 'no raw_text in result structure')
                    raise ProjectQBackendError(
                        'Result structure does not contain proper histogram. raw_text field: %s' % raw_text)
            else:
                self._quantum_inspire_result = None
                return

            counts = QIBackend.format_histogram(self._quantum_inspire_result['histogram'],
                                                number_of_qubits=self.nqubits, number_of_runs=self._num_runs)
            measured = self._calculate_probabilities(counts)

            class QB():
                def __init__(self, ID):
                    self.id = ID

            # register measurement result
            if self._verbose:
                print('QIBackend: counts {0}'.format(counts))
                print('QIBackend: measured {0}'.format(measured))
            for ID in self._measured_ids:
                location = self._logical_to_physical(ID)

                result = int(measured[location])
                self.main_engine.set_measurement_result(QB(ID), result)
            self._reset()
        except TypeError as ex:
            raise ProjectQBackendError("Failed to run the circuit. Aborting.")

    def receive(self, command_list):
        """
        Receives a command list and, for each command, stores it until
        completion.

        Args:
            command_list: List of commands to execute
        """
        for cmd in command_list:
            if not cmd.gate == FlushGate():
                self._store(cmd)
            else:
                self._run()
                self._reset()

    """ Mapping of gate names from our gate objects to the cQASM representation."""
    _gate_names = {str(Tdag): "Tdag", str(Sdag): "Sdag"}