""" Quantum Inspire SDK

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

import io
import logging
import time
import uuid

from qiskit._result import Result
from qiskit.backends import BaseBackend

from quantuminspire.qiskit.circuit_parser import CircuitToString
from quantuminspire.exceptions import QisKitBackendError


class QiSimulatorPy(BaseBackend):

    DEFAULT_CONFIGURATION = {
        'name': 'local_qi_simulator_py',
        'url': 'https://www.quantum-inspire.com/',
        'description': 'A Quantum Inspire Simulator for QASM files',
        'qi_backend_name': 'QX single-node simulator',
        'basis_gates': 'x,y,z,h,s,cx,ccx,u1,u2,u3,id,snapshot',
        'coupling_map': 'all-to-all',
        'simulator': True,
        'local': True
    }

    def __init__(self, api, configuration=None, logger=logging):
        """ Python implementation of a quantum simulator using Quantum Inspire API.

        Args:
            api (QuantumInspireApi): The interface instance to the Quantum Inspire API.
            configuration (dict, optional): The configuration of the quantum inspire backend.
                                            A default configuration is used when no value is given.
        """
        super().__init__(configuration or QiSimulatorPy.DEFAULT_CONFIGURATION)
        self.__backend_name = self.configuration['qi_backend_name']
        self.__backend = api.get_backend_type_by_name(self.__backend_name)
        self.__logger = logger
        self.__api = api
        self.execution_results = None
        self.number_of_shots = None
        self.compiled_qasm = None

    def run(self, job):
        """ Runs a quantum job on the Quantum Inspire platform.

        Args:
            job (dict): The quantum job with the qiskit algorithm and quantum inspire backend.

        Returns:
            Result: The result of the executed job.
        """
        start_time = time.time()

        self.__validate(job)
        self.number_of_shots = job['config']['shots']

        circuits = job['circuits']
        job_identifier = str(uuid.uuid4())
        result_list = [self._run_circuit(circuit) for circuit in circuits]
        execution_time = time.time() - start_time
        result = {'backend': self.__backend_name, 'id': job['id'], 'job_id': job_identifier,
                  'result': result_list, 'status': 'COMPLETED', 'success': True,
                  'time_taken': execution_time}
        return Result(result)

    def _generate_cqasm(self, compiled_circuits):
        """ Generates the CQASM from the qiskit algorithm.

        Args: compiled_circuits (dict): The compiled circuits from qiskit.

        Returns:
            str: The CQASM code that can be sent to the Quantum Inspire API.
        """
        parser = CircuitToString()
        number_of_qubits = compiled_circuits['header']['number_of_qubits']
        operations = compiled_circuits['operations']
        self.__logger.info('generate_cqasm: %d qubits\n' % number_of_qubits)
        with io.StringIO() as stream:
            stream.write('version 1.0\n')
            stream.write('# cqasm generated by QI backend for QisKit\n')
            stream.write('qubits %d\n' % number_of_qubits)

            for circuit in operations:
                gate_name = '_%s' % circuit['name'].lower()
                gate_function = getattr(parser, gate_name)
                line = gate_function(circuit)
                if isinstance(line, str):
                    stream.write(line)

            stream.write('.measurement\n')
            for qubit_index in range(number_of_qubits):
                stream.write('   measure q[%d]\n' % qubit_index)
            return stream.getvalue()

    def _run_circuit(self, circuit):
        """Run a circuit and return a single Result object.

        Args:
            circuit (dict): JSON circuit from quantum object with circuits list.

        Raises:
            QisKitBackendError: if an error occurred during execution by the backend.

        Returns:
            Dict: A dictionary with results; containing the data, execution time, status, etc.
        """
        start_time = time.time()
        self.__logger.info('\nRunning circuit... ({00} shots)'.format(self.number_of_shots))

        compiled_circuit = circuit['compiled_circuit']
        self.compiled_qasm = self._generate_cqasm(compiled_circuit)
        self.execution_results = self.__api.execute_qasm(self.compiled_qasm, self.__backend, self.number_of_shots)
        if len(self.execution_results['histogram']) == 0:
            raise QisKitBackendError('Result from backend contains no histogram data!')

        histogram = self.execution_results['histogram'].items()
        counts = {key: value * self.number_of_shots for key, value in histogram}
        data = {'counts': counts, 'snapshots': dict()}

        execution_time = time.time() - start_time
        self.__logger.info('Execution done in {0:.2g} seconds.\n'.format(execution_time))
        return {'name': circuit['name'], 'seed': None, 'shots': self.number_of_shots,
                'data': data, 'status': 'DONE', 'success': True, 'time_taken': execution_time}

    def __validate(self, quantum_object):
        """ Validates the number of shots and the operation names of the compiled qiskit code.

        Args:
            quantum_object (dict): The quantum job with the qiskit algorithm and quantum inspire backend.
        """
        circuits = quantum_object['circuits']
        number_of_shots = quantum_object['config']['shots']

        if number_of_shots == 1:
            self.__logger.error('The behavior of getting statevector from simulators'
                                'by setting shots=1 is deprecated and will be removed.'
                                'Use the local_statevector_simulator instead, or place'
                                'explicit snapshot instructions.')
            raise QisKitBackendError('Single shot execution not possible!')

        for circuit in circuits:
            operations = circuit['compiled_circuit']['operations']
            operation_names = [operation['name'] for operation in operations]
            if 'measure' not in operation_names:
                self.__logger.warning("No measurements in circuit '%s', classical register will remain all zeros.",
                                      circuit['name'])