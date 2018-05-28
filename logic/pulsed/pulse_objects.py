# -*- coding: utf-8 -*-

"""
This file contains the Qudi data object classes needed for pulse sequence generation.

Qudi is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

Qudi is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with Qudi. If not, see <http://www.gnu.org/licenses/>.

Copyright (c) the Qudi Developers. See the COPYRIGHT.txt file at the
top-level directory of this distribution and at <https://github.com/Ulm-IQO/qudi/>
"""

import copy
import os
import sys
import inspect
import importlib
from collections import OrderedDict

from logic.pulsed.sampling_functions import SamplingFunctions as sf
from core.util.modules import get_main_dir


class PulseBlockElement(object):
    """
    Object representing a single atomic element in a pulse block.

    This class can build waiting times, sine waves, etc. The pulse block may
    contain many Pulse_Block_Element Objects. These objects can be displayed in
    a GUI as single rows of a Pulse_Block.
    """
    def __init__(self, init_length_s=10e-9, increment_s=0, pulse_function=None, digital_high=None):
        """
        The constructor for a Pulse_Block_Element needs to have:

        @param float init_length_s: an initial length of the element, this parameters should not be
                                    zero but must have a finite value.
        @param float increment_s: the number which will be incremented during each repetition of
                                  this element.
        @param dict pulse_function: dictionary with keys being the qudi analog channel string
                                    descriptors ('a_ch1', 'a_ch2' etc.) and the corresponding
                                    objects being instances of the mathematical function objects
                                    provided by SamplingFunctions class.
        @param dict digital_high: dictionary with keys being the qudi digital channel string
                                  descriptors ('d_ch1', 'd_ch2' etc.) and the corresponding objects
                                  being boolean values describing if the channel should be logical
                                  low (False) or high (True).
                                  For 3 digital channel it may look like:
                                  {'d_ch1': True, 'd_ch2': False, 'd_ch5': False}
        """
        # FIXME: Sanity checks need to be implemented here
        self.init_length_s = init_length_s
        self.increment_s = increment_s
        if pulse_function is None:
            self.pulse_function = OrderedDict()
        else:
            self.pulse_function = pulse_function
        if digital_high is None:
            self.digital_high = OrderedDict()
        else:
            self.digital_high = digital_high

        # determine set of used digital and analog channels
        self.analog_channels = set(self.pulse_function)
        self.digital_channels = set(self.digital_high)
        self.channel_set = self.analog_channels.union(self.digital_channels)

    def get_dict_representation(self):
        dict_repr = dict()
        dict_repr['init_length_s'] = self.init_length_s
        dict_repr['increment_s'] = self.increment_s
        dict_repr['digital_high'] = self.digital_high
        dict_repr['pulse_function'] = dict()
        for chnl, func in self.pulse_function.items():
            dict_repr['pulse_function'][chnl] = func.get_dict_representation()
        return dict_repr

    @staticmethod
    def element_from_dict(element_dict):
        for chnl, sample_dict in element_dict['pulse_function'].items():
            sf_class = getattr(sf, sample_dict['name'])
            element_dict['pulse_function'][chnl] = sf_class(**sample_dict['params'])
        return PulseBlockElement(**element_dict)


class PulseBlock(object):
    """
    Collection of Pulse_Block_Elements which is called a Pulse_Block.
    """
    def __init__(self, name, element_list=None):
        """
        The constructor for a Pulse_Block needs to have:

        @param str name: chosen name for the Pulse_Block
        @param list element_list: which contains the Pulse_Block_Element Objects forming a
                                  Pulse_Block, e.g. [Pulse_Block_Element, Pulse_Block_Element, ...]
        """
        self.name = name
        self.element_list = list() if element_list is None else element_list
        self.init_length_s = 0.0
        self.increment_s = 0.0
        self.analog_channels = set()
        self.digital_channels = set()
        self.channel_set = set()
        self.refresh_parameters()
        return

    def refresh_parameters(self):
        """ Initialize the parameters which describe this Pulse_Block object.

        The information is gained from all the Pulse_Block_Element objects,
        which are attached in the element_list.
        """
        # the Pulse_Block parameters
        self.init_length_s = 0.0
        self.increment_s = 0.0
        self.channel_set = set()

        for elem in self.element_list:
            self.init_length_s += elem.init_length_s
            self.increment_s += elem.increment_s

            if not self.channel_set:
                self.channel_set = elem.channel_set
            elif self.channel_set != elem.channel_set:
                raise ValueError('Usage of different sets of analog and digital channels in the '
                                 'same PulseBlock is prohibited.\nPulseBlock creation failed!\n'
                                 'Used channel sets are:\n{0}\n{1}'.format(self.channel_set,
                                                                           elem.channel_set))
                break
        self.analog_channels = {chnl for chnl in self.channel_set if chnl.startswith('a')}
        self.digital_channels = {chnl for chnl in self.channel_set if chnl.startswith('d')}
        return

    def replace_element(self, position, element):
        if not isinstance(element, PulseBlockElement) or len(self.element_list) <= position:
            return -1

        if element.channel_set != self.channel_set:
            raise ValueError('Usage of different sets of analog and digital channels in the '
                             'same PulseBlock is prohibited. Used channel sets are:\n{0}\n{1}'
                             ''.format(self.channel_set, element.channel_set))
            return -1

        self.init_length_s -= self.element_list[position].init_length_s
        self.increment_s -= self.element_list[position].increment_s
        self.init_length_s += element.init_length_s
        self.increment_s += element.increment_s
        self.element_list[position] = copy.deepcopy(element)
        return 0

    def delete_element(self, position):
        if len(self.element_list) <= position:
            return -1

        self.init_length_s -= self.element_list[position].init_length_s
        self.increment_s -= self.element_list[position].increment_s
        del self.element_list[position]
        if len(self.element_list) == 0:
            self.init_length_s = 0.0
            self.increment_s = 0.0
        return 0

    def insert_element(self, position, element):
        """ Insert a PulseBlockElement at the given position. The old elements at this position and
        all consecutive elements after that will be shifted to higher indices.

        @param int position: position in the element list
        @param PulseBlockElement element: PulseBlockElement instance
        """
        if not isinstance(element, PulseBlockElement) or len(self.element_list) < position:
            return -1

        if not self.channel_set:
            self.channel_set = element.channel_set
            self.analog_channels = {chnl for chnl in self.channel_set if chnl.startswith('a')}
            self.digital_channels = {chnl for chnl in self.channel_set if chnl.startswith('d')}
        elif element.channel_set != self.channel_set:
            raise ValueError('Usage of different sets of analog and digital channels in the '
                             'same PulseBlock is prohibited. Used channel sets are:\n{0}\n{1}'
                             ''.format(self.channel_set, element.channel_set))
            return -1

        self.init_length_s += element.init_length_s
        self.increment_s += element.increment_s

        self.element_list.insert(position, copy.deepcopy(element))
        return 0

    def append_element(self, element, at_beginning=False):
        """
        """
        position = 0 if at_beginning else len(self.element_list)
        return self.insert_element(position=position, element=element)

    def get_dict_representation(self):
        dict_repr = dict()
        dict_repr['name'] = self.name
        dict_repr['element_list'] = list()
        for element in self.element_list:
            dict_repr['element_list'].append(element.get_dict_representation())
        return dict_repr

    @staticmethod
    def block_from_dict(block_dict):
        for ii, element_dict in enumerate(block_dict['element_list']):
            block_dict['element_list'][ii] = PulseBlockElement.element_from_dict(element_dict)
        return PulseBlock(**block_dict)


class PulseBlockEnsemble(object):
    """
    Represents a collection of PulseBlock objects which is called a PulseBlockEnsemble.

    This object is used as a construction plan to create one sampled file.
    """
    def __init__(self, name, block_list=None, rotating_frame=True):
        """
        The constructor for a Pulse_Block_Ensemble needs to have:

        @param str name: chosen name for the PulseBlockEnsemble
        @param list block_list: contains the PulseBlock names with their number of repetitions,
                                e.g. [(name, repetitions), (name, repetitions), ...])
        @param bool rotating_frame: indicates whether the phase should be preserved for all the
                                    functions.
        """
        # FIXME: Sanity checking needed here
        self.name = name
        self.rotating_frame = rotating_frame
        if isinstance(block_list, list):
            self.block_list = block_list
        else:
            self.block_list = list()

        # Dictionary container to store information related to the actually sampled
        # Waveform like pulser settings used during sampling (sample_rate, activation_config etc.)
        # and additional information about the discretization of the waveform (timebin positions of
        # the PulseBlockElement transitions etc.) as well as the names of the created waveforms.
        # This container will be populated during sampling and will be emptied upon deletion of the
        # corresponding waveforms from the pulse generator
        self.sampling_information = dict()
        # Dictionary container to store additional information about for measurement settings
        # (ignore_lasers, controlled_variable, alternating etc.).
        # This container needs to be populated by the script creating the PulseBlockEnsemble
        # before saving it. (e.g. in generate methods in PulsedObjectGenerator class)
        self.measurement_information = dict()
        return

    def replace_block(self, position, block_name, reps=None):
        """
        """
        if not isinstance(block_name, str) or len(self.block_list) <= position:
            return -1

        if reps is None:
            self.block_list[position][0] = block_name
        elif reps >= 0:
            self.block_list[position] = (block_name, reps)
        else:
            return -1
        return 0

    def delete_block(self, position):
        """
        """
        if len(self.block_list) <= position:
            return -1

        del self.block_list[position]
        return 0

    def insert_block(self, position, block_name, reps=0):
        """ Insert a PulseBlock at the given position. The old block at this position and all
        consecutive blocks after that will be shifted to higher indices.

        @param int position: position in the block list
        @param str block_name: PulseBlock name
        @param int reps: Block repetitions. Zero means single playback of the block.
        """
        if not isinstance(block_name, str) or len(self.block_list) < position or reps < 0:
            return -1

        self.block_list.insert(position, (block_name, reps))
        return 0

    def append_block(self, block_name, reps=0, at_beginning=False):
        """ Append either at the front or at the back.

        @param str block_name: PulseBlock name
        @param int reps: Block repetitions. Zero means single playback of the block.
        @param bool at_beginning: If False append to end (default), if True insert at beginning.
        """
        position = 0 if at_beginning else len(self.block_list)
        return self.insert_block(position=position, block_name=block_name, reps=reps)

    def get_dict_representation(self):
        dict_repr = dict()
        dict_repr['name'] = self.name
        dict_repr['rotating_frame'] = self.rotating_frame
        dict_repr['block_list'] = self.block_list
        dict_repr['sampling_information'] = self.sampling_information
        dict_repr['measurement_information'] = self.measurement_information
        return dict_repr

    @staticmethod
    def ensemble_from_dict(ensemble_dict):
        new_ens = PulseBlockEnsemble(name=ensemble_dict['name'],
                                     block_list=ensemble_dict['block_list'],
                                     rotating_frame=ensemble_dict['rotating_frame'])
        new_ens.sampling_information = ensemble_dict['sampling_information']
        new_ens.measurement_information = ensemble_dict['measurement_information']
        return new_ens


class PulseSequence(object):
    """
    Higher order object for sequence capability.

    Represents a playback procedure for a number of PulseBlockEnsembles. Unused for pulse
    generator hardware without sequencing functionality.
    """
    def __init__(self, name, ensemble_list=None, rotating_frame=False):
        """
        The constructor for a PulseSequence objects needs to have:

        @param str name: the actual name of the sequence
        @param list ensemble_list: list containing a tuple of two entries:
                                          [(PulseBlockEnsemble name, seq_param),
                                           (PulseBlockEnsemble name, seq_param), ...]
                                          The seq_param is a dictionary, where the various sequence
                                          parameters are saved with their keywords and the
                                          according parameter (as item).
                                          Available parameters are:
                                          'repetitions': The number of repetitions for that sequence
                                                         step. (Default 0)
                                                         0 meaning the step is played once.
                                                         Set to -1 for infinite looping.
                                          'go_to':   The sequence step index to jump to after
                                                     having played all repetitions or receiving a
                                                     jump trigger. (Default -1)
                                                     Indices starting at 0 for first step.
                                                     Set to -1 to follow up with the next step.
                                          'event_jump_to': The input trigger channel index used to
                                                          jump to the step defined in 'jump_to'.
                                                          (Default -1)
                                                          Indices starting at 0 for first trigger
                                                          input channel.
                                                          Set to -1 for not listening to triggers.

                                          If only 'repetitions' are in the dictionary, then the dict
                                          will look like:
                                            seq_param = {'repetitions': 41}
                                          and so the respective sequence step will play 42 times.
        @param bool rotating_frame: indicates, whether the phase has to be preserved in all
                                    analog signals ACROSS different waveforms
        """
        self.name = name
        self.rotating_frame = rotating_frame
        self.ensemble_list = list() if ensemble_list is None else ensemble_list
        self.is_finite = True
        self.refresh_parameters()

        # self.sampled_ensembles = OrderedDict()
        # Dictionary container to store information related to the actually sampled
        # Waveforms like pulser settings used during sampling (sample_rate, activation_config etc.)
        # and additional information about the discretization of the waveform (timebin positions of
        # the PulseBlockElement transitions etc.)
        # This container is not necessary for the sampling process but serves only the purpose of
        # holding optional information for different modules.
        self.sampling_information = dict()
        # Dictionary container to store additional information about for measurement settings
        # (ignore_lasers, controlled_values, alternating etc.).
        # This container needs to be populated by the script creating the PulseSequence
        # before saving it.
        self.measurement_information = dict()
        return

    def refresh_parameters(self):
        self.is_finite = True
        for ensemble_name, params in self.ensemble_list:
            if params['repetitions'] < 0:
                self.is_finite = False
                break
        return

    def replace_ensemble(self, position, ensemble_name, seq_param=None):
        """ Replace a sequence step at a given position.

        @param int position: position in the ensemble list
        @param str ensemble_name: PulseBlockEnsemble name
        @param dict seq_param: Sequence step parameter dictionary. Use present one if None.
        """
        if not isinstance(ensemble_name, str) or len(self.ensemble_list) <= position:
            return -1

        if seq_param is None:
            self.ensemble_list[position][0] = ensemble_name
        else:
            self.ensemble_list[position] = (ensemble_name, seq_param.copy())
            if seq_param['repetitions'] < 0 and self.is_finite:
                self.is_finite = False
            elif seq_param['repetitions'] >= 0 and not self.is_finite:
                self.refresh_parameters()
        return 0

    def delete_ensemble(self, position):
        """ Delete an ensemble at a given position

        @param int position: position within the list self.ensemble_list.
        """
        if len(self.ensemble_list) <= position:
            return -1

        refresh = True if self.ensemble_list[position][1]['repetitions'] < 0 else False

        del self.ensemble_list[position]

        if refresh:
            self.refresh_parameters()
        return 0

    def insert_ensemble(self, position, ensemble_name, seq_param):
        """ Insert a sequence step at the given position. The old step at this position and all
        consecutive steps after that will be shifted to higher indices.

        @param int position: position in the ensemble list
        @param str ensemble_name: PulseBlockEnsemble name
        @param dict seq_param: Sequence step parameter dictionary.
        """
        if not isinstance(ensemble_name, str) or len(self.ensemble_list) < position:
            return -1

        self.ensemble_list.insert(position, (ensemble_name, seq_param.copy()))

        if seq_param['repetitions'] < 0:
            self.is_finite = False
        return 0

    def append_ensemble(self, ensemble_name, seq_param, at_beginning=False):
        """ Append either at the front or at the back.

        @param str ensemble_name: PulseBlockEnsemble name
        @param dict seq_param: Sequence step parameter dictionary.
        @param bool at_beginning: If False append to end (default), if True insert at beginning.
        """
        position = 0 if at_beginning else len(self.ensemble_list)
        return self.insert_ensemble(position=position,
                                    ensemble_name=ensemble_name,
                                    seq_param=seq_param)

    def get_dict_representation(self):
        dict_repr = dict()
        dict_repr['name'] = self.name
        dict_repr['rotating_frame'] = self.rotating_frame
        dict_repr['ensemble_list'] = self.ensemble_list
        dict_repr['sampling_information'] = self.sampling_information
        dict_repr['measurement_information'] = self.measurement_information
        return dict_repr

    @staticmethod
    def sequence_from_dict(sequence_dict):
        new_seq = PulseSequence(name=sequence_dict['name'],
                                ensemble_list=sequence_dict['ensemble_list'],
                                rotating_frame=sequence_dict['rotating_frame'])
        new_seq.sampling_information = sequence_dict['sampling_information']
        new_seq.measurement_information = sequence_dict['measurement_information']
        return new_seq


class PredefinedGeneratorBase:
    """
    Base class for PulseObjectGenerator and predefined generator classes containing the actual
    "generate_"-methods.

    This class holds a protected reference to the SequenceGeneratorLogic and provides read-only
    access via properties to various attributes of the logic module.
    SequenceGeneratorLogic logger is also accessible via this base class and can be used as in any
    qudi module (e.g. self.log.error(...)).
    Also provides helper methods to simplify sequence/ensemble generation.
    """
    def __init__(self, sequencegeneratorlogic):
        # Keep protected reference to the SequenceGeneratorLogic
        self.__sequencegeneratorlogic = sequencegeneratorlogic

    @property
    def log(self):
        return self.__sequencegeneratorlogic.log

    @property
    def pulse_generator_settings(self):
        return self.__sequencegeneratorlogic.pulse_generator_settings

    @property
    def generation_parameters(self):
        return self.__sequencegeneratorlogic.generation_parameters

    @property
    def channel_set(self):
        channels = self.pulse_generator_settings.get('activation_config')
        if channels is None:
            channels = ('', set())
        return channels[1]

    @property
    def analog_channels(self):
        return {chnl for chnl in self.channel_set if chnl.startswith('a')}

    @property
    def digital_channels(self):
        return {chnl for chnl in self.channel_set if chnl.startswith('d')}

    @property
    def laser_channel(self):
        return self.generation_parameters.get('laser_channel')

    @property
    def sync_channel(self):
        channel = self.generation_parameters.get('sync_channel')
        return None if channel == '' else channel

    @property
    def gate_channel(self):
        channel = self.generation_parameters.get('gate_channel')
        return None if channel == '' else channel

    @property
    def analog_trigger_voltage(self):
        return self.generation_parameters.get('analog_trigger_voltage')

    @property
    def laser_delay(self):
        return self.generation_parameters.get('laser_delay')

    @property
    def microwave_channel(self):
        channel = self.generation_parameters.get('microwave_channel')
        return None if channel == '' else channel

    @property
    def microwave_frequency(self):
        return self.generation_parameters.get('microwave_frequency')

    @property
    def microwave_amplitude(self):
        return self.generation_parameters.get('microwave_amplitude')

    @property
    def laser_length(self):
        return self.generation_parameters.get('laser_length')

    @property
    def wait_time(self):
        return self.generation_parameters.get('wait_time')

    @property
    def rabi_period(self):
        return self.generation_parameters.get('rabi_period')

    ################################################################################################
    #                                   Helper methods                                          ####
    ################################################################################################
    def _get_idle_element(self, length, increment):
        """
        Creates an idle pulse PulseBlockElement

        @param float length: idle duration in seconds
        @param float increment: idle duration increment in seconds

        @return: PulseBlockElement, the generated idle element
        """
        # Create idle element
        return PulseBlockElement(init_length_s=length,
                                 increment_s=increment,
                                 pulse_function={chnl: sf.Idle() for chnl in self.analog_channels},
                                 digital_high={chnl: False for chnl in self.digital_channels})

    def _get_trigger_element(self, length, increment, channels):
        """
        Creates a trigger PulseBlockElement

        @param float length: trigger duration in seconds
        @param float increment: trigger duration increment in seconds
        @param str|list channels: The pulser channel(s) to be triggered.

        @return: PulseBlockElement, the generated trigger element
        """
        if isinstance(channels, str):
            channels = [channels]

        # input params for element generation
        pulse_function = {chnl: sf.Idle() for chnl in self.analog_channels}
        digital_high = {chnl: False for chnl in self.digital_channels}

        # Determine analogue or digital trigger channel and set channels accordingly.
        for channel in channels:
            if channel.startswith('d'):
                digital_high[channel] = True
            else:
                pulse_function[channel] = sf.DC(voltage=self.analog_trigger_voltage)

        # return trigger element
        return PulseBlockElement(init_length_s=length,
                                 increment_s=increment,
                                 pulse_function=pulse_function,
                                 digital_high=digital_high)

    def _get_laser_element(self, length, increment):
        """
        Creates laser trigger PulseBlockElement

        @param float length: laser pulse duration in seconds
        @param float increment: laser pulse duration increment in seconds

        @return: PulseBlockElement, two elements for laser and gate trigger (delay element)
        """
        return self._get_trigger_element(length=length,
                                         increment=increment,
                                         channels=self.laser_channel)

    def _get_laser_gate_element(self, length, increment):
        """
        """
        laser_gate_element = self._get_laser_element(length=length,
                                                     increment=increment)
        if self.gate_channel:
            if self.gate_channel.startswith('d'):
                laser_gate_element.digital_high[self.gate_channel] = True
            else:
                laser_gate_element.pulse_function[self.gate_channel] = sf.DC(
                    voltage=self.analog_trigger_voltage)
        return laser_gate_element

    def _get_delay_element(self):
        """
        Creates an idle element of length of the laser delay

        @return PulseBlockElement: The delay element
        """
        return self._get_idle_element(length=self.laser_delay,
                                      increment=0)

    def _get_delay_gate_element(self):
        """
        Creates a gate trigger of length of the laser delay.
        If no gate channel is specified will return a simple idle element.

        @return PulseBlockElement: The delay element
        """
        if self.gate_channel:
            return self._get_trigger_element(length=self.laser_delay,
                                             increment=0,
                                             channels=self.gate_channel)
        else:
            return self._get_delay_element()

    def _get_sync_element(self):
        """

        """
        return self._get_trigger_element(length=50e-9,
                                         increment=0,
                                         channels=self.sync_channel)

    def _get_mw_element(self, length, increment, amp=None, freq=None, phase=None):
        """
        Creates a MW pulse PulseBlockElement

        @param float length: MW pulse duration in seconds
        @param float increment: MW pulse duration increment in seconds
        @param float freq: MW frequency in case of analogue MW channel in Hz
        @param float amp: MW amplitude in case of analogue MW channel in V
        @param float phase: MW phase in case of analogue MW channel in deg

        @return: PulseBlockElement, the generated MW element
        """
        if self.microwave_channel.startswith('d'):
            mw_element = self._get_trigger_element(
                length=length,
                increment=increment,
                channels=self.microwave_channel)
        else:
            mw_element = self._get_idle_element(
                length=length,
                increment=increment)
            mw_element.pulse_function[self.microwave_channel] = sf.Sin(amplitude=amp,
                                                                       frequency=freq,
                                                                       phase=phase)
        return mw_element

    def _get_multiple_mw_element(self, length, increment, amps=None, freqs=None, phases=None):
        """
        Creates single, double or triple sine mw element.

        @param float length: MW pulse duration in seconds
        @param float increment: MW pulse duration increment in seconds
        @param amps: list containing the amplitudes
        @param freqs: list containing the frequencies
        @param phases: list containing the phases
        @return: PulseBlockElement, the generated MW element
        """
        if isinstance(amps, (int, float)):
            amps = [amps]
        if isinstance(freqs, (int, float)):
            freqs = [freqs]
        if isinstance(phases, (int, float)):
            phases = [phases]

        if self.microwave_channel.startswith('d'):
            mw_element = self._get_trigger_element(
                length=length,
                increment=increment,
                channels=self.microwave_channel)
        else:
            mw_element = self._get_idle_element(
                length=length,
                increment=increment)

            sine_number = min(len(amps), len(freqs), len(phases))

            if sine_number < 2:
                mw_element.pulse_function[self.microwave_channel] = sf.Sin(amplitude=amps[0],
                                                                           frequency=freqs[0],
                                                                           phase=phases[0])
            elif sine_number == 2:
                mw_element.pulse_function[self.microwave_channel] = sf.DoubleSin(
                    amplitude_1=amps[0],
                    amplitude_2=amps[1],
                    frequency_1=freqs[0],
                    frequency_2=freqs[1],
                    phase_1=phases[0],
                    phase_2=phases[1])
            else:
                mw_element.pulse_function[self.microwave_channel] = sf.TripleSin(
                    amplitude_1=amps[0],
                    amplitude_2=amps[1],
                    amplitude_3=amps[2],
                    frequency_1=freqs[0],
                    frequency_2=freqs[1],
                    frequency_3=freqs[2],
                    phase_1=phases[0],
                    phase_2=phases[1],
                    phase_3=phases[2])
        return mw_element

    def _get_mw_laser_element(self, length, increment, amp=None, freq=None, phase=None):
        """

        @param length:
        @param increment:
        @param amp:
        @param freq:
        @param phase:
        @return:
        """
        mw_laser_element = self._get_mw_element(length=length,
                                                increment=increment,
                                                amp=amp,
                                                freq=freq,
                                                phase=phase)
        if self.laser_channel.startswith('d'):
            mw_laser_element.digital_high[self.laser_channel] = True
        else:
            mw_laser_element.pulse_function[self.laser_channel] = sf.DC(
                voltage=self.analog_trigger_voltage)
        return mw_laser_element

    def _get_ensemble_count_length(self, ensemble, created_blocks):
        """

        @param ensemble:
        @param created_blocks:
        @return:
        """
        if self.gate_channel:
            length = self.laser_length + self.laser_delay
        else:
            blocks = {block.name: block for block in created_blocks}
            length = 0.0
            for block_name, reps in ensemble.block_list:
                length += blocks[block_name].init_length_s * (reps + 1)
                length += blocks[block_name].increment_s * ((reps ** 2 + reps) / 2)
        return length


class PulseObjectGenerator(PredefinedGeneratorBase):
    """

    """
    def __init__(self, sequencegeneratorlogic):
        # Initialize base class
        super().__init__(sequencegeneratorlogic)

        # dictionary containing references to all generation methods imported from generator class
        # modules. The keys are the method names excluding the prefix "generate_".
        self._generate_methods = dict()
        # nested dictionary with keys being the generation method names and values being a
        # dictionary containing all keyword arguments as keys with their default value
        self._generate_method_parameters = dict()

        # import path for generator modules from default dir (logic.predefined_generate_methods)
        path_list = [os.path.join(get_main_dir(), 'logic', 'pulsed', 'predefined_generate_methods')]
        # import path for generator modules from non-default directory if a path has been given
        if isinstance(sequencegeneratorlogic.additional_methods_dir, str):
            path_list.append(sequencegeneratorlogic.additional_methods_dir)

        # Import predefined generator modules and get a list of generator classes
        generator_classes = self.__import_external_generators(paths=path_list)

        # create an instance of each class and put them in a temporary list
        generator_instances = [cls(sequencegeneratorlogic) for cls in generator_classes]

        # add references to all generate methods in each instance to a dict
        self.__populate_method_dict(instance_list=generator_instances)

        # populate parameters dictionary from generate method signatures
        self.__populate_parameter_dict()

    @property
    def predefined_generate_methods(self):
        return self._generate_methods

    @property
    def predefined_method_parameters(self):
        return self._generate_method_parameters.copy()

    def __import_external_generators(self, paths):
        """
        Helper method to import all modules from directories contained in paths.
        Find all classes in those modules that inherit exclusively from PredefinedGeneratorBase
        class and return a list of them.

        @param iterable paths: iterable containing paths to import modules from
        @return list: A list of imported valid generator classes
        """
        class_list = list()
        for path in paths:
            if not os.path.exists(path):
                self.log.error('Unable to import generate methods from "{0}".\n'
                               'Path does not exist.'.format(path))
                continue
            # Get all python modules to import from.
            # The assumption is that in the path, there are *.py files,
            # which contain only generator classes!
            module_list = [name[:-3] for name in os.listdir(path) if
                           os.path.isfile(os.path.join(path, name)) and name.endswith('.py')]

            # append import path to sys.path
            sys.path.append(path)

            # Go through all modules and create instances of each class found.
            for module_name in module_list:
                # import module
                mod = importlib.import_module('{0}'.format(module_name))
                importlib.reload(mod)
                # get all generator class references defined in the module
                tmp_list = [m[1] for m in inspect.getmembers(mod, self.is_generator_class)]
                # append to class_list
                class_list.extend(tmp_list)
        return class_list

    def __populate_method_dict(self, instance_list):
        """
        Helper method to populate the dictionaries containing all references to callable generate
        methods contained in generator instances passed to this method.

        @param list instance_list: List containing instances of generator classes
        """
        self._generate_methods = dict()
        for instance in instance_list:
            for method_name, method_ref in inspect.getmembers(instance, inspect.ismethod):
                if method_name.startswith('generate_'):
                    self._generate_methods[method_name[9:]] = method_ref
        return

    def __populate_parameter_dict(self):
        """
        Helper method to populate the dictionary containing all possible keyword arguments from all
        generate methods.
        """
        self._generate_method_parameters = dict()
        for method_name, method in self._generate_methods.items():
            method_signature = inspect.signature(method)
            param_dict = dict()
            for name, param in method_signature.parameters.items():
                param_dict[name] = None if param.default is param.empty else param.default

            self._generate_method_parameters[method_name] = param_dict
        return

    @staticmethod
    def is_generator_class(obj):
        """
        Helper method to check if an object is a valid generator class.

        @param object obj: object to check
        @return bool: True if obj is a valid generator class, False otherwise
        """
        if inspect.isclass(obj):
            return PredefinedGeneratorBase in obj.__bases__ and len(obj.__bases__) == 1
        return False


