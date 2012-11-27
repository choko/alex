#!/usr/bin/env python

import time
import multiprocessing
import argparse

if __name__ == "__main__":
    import autopath

from SDS.components.hub import Hub
from SDS.components.hub.aio import AudioIO
from SDS.components.hub.vad import VAD
from SDS.components.hub.asr import ASR
from SDS.components.hub.slu import SLU
from SDS.components.hub.dm import DM
from SDS.components.hub.nlg import NLG
from SDS.components.hub.tts import TTS
from SDS.components.hub.messages import Command
from SDS.utils.config import Config

class AudioHub(Hub):
    def __init__(self, cfg):
        self.cfg = cfg

    def run(self):
        # AIO pipes
        # used to send commands to VoipIO
        aio_commands, aio_child_commands = multiprocessing.Pipe()
        # I read from this connection recorded audio
        aio_record, aio_child_record = multiprocessing.Pipe()
        # I write in audio to be played
        aio_play, aio_child_play = multiprocessing.Pipe()
        # I read from this to get played audio
        aio_played, aio_child_played = multiprocessing.Pipe()

        # VAD pipes
        # used to send commands to VAD
        vad_commands, vad_child_commands = multiprocessing.Pipe()
        # used to read output audio from VAD
        vad_audio_out, vad_child_audio_out = multiprocessing.Pipe()

        # ASR pipes
        # used to send commands to ASR
        asr_commands, asr_child_commands = multiprocessing.Pipe()
        # used to read ASR hypotheses
        asr_hypotheses_out, asr_child_hypotheses = multiprocessing.Pipe()

        # SLU pipes
        # used to send commands to SLU
        slu_commands, slu_child_commands = multiprocessing.Pipe()
        # used to read SLU hypotheses
        slu_hypotheses_out, slu_child_hypotheses = multiprocessing.Pipe()

        # DM pipes
        # used to send commands to DM
        dm_commands, dm_child_commands = multiprocessing.Pipe()
        # used to read DM actions
        dm_actions_out, dm_child_actions = multiprocessing.Pipe()

        # NLG pipes
        # used to send commands to NLG
        nlg_commands, nlg_child_commands = multiprocessing.Pipe()
        # used to read NLG output
        nlg_text_out, nlg_child_text = multiprocessing.Pipe()

        # TTS pipes
        # used to send commands to TTS
        tts_commands, tts_child_commands = multiprocessing.Pipe()


        command_connections = [aio_commands, vad_commands, asr_commands,
                               slu_commands, dm_commands, nlg_commands,
                               tts_commands]

        non_command_connections = [aio_record, aio_child_record,
                                   aio_play, aio_child_play,
                                   aio_played, aio_child_played,
                                   vad_audio_out, vad_child_audio_out,
                                   asr_hypotheses_out, asr_child_hypotheses,
                                   slu_hypotheses_out, slu_child_hypotheses,
                                   dm_actions_out, dm_child_actions,
                                   nlg_text_out, nlg_child_text]


        # create the hub components
        aio = AudioIO(self.cfg, aio_child_commands, aio_child_record, aio_child_play, aio_child_played)
        vad = VAD(self.cfg, vad_child_commands, aio_record, aio_played, vad_child_audio_out)
        asr = ASR(self.cfg, asr_child_commands, vad_audio_out, asr_child_hypotheses)
        slu = SLU(self.cfg, slu_child_commands, asr_hypotheses_out, slu_child_hypotheses)
        dm  =  DM(self.cfg,  dm_child_commands, slu_hypotheses_out, dm_child_actions)
        nlg = NLG(self.cfg, nlg_child_commands, dm_actions_out, nlg_child_text)
        tts = TTS(self.cfg, tts_child_commands, nlg_text_out, aio_play)

        # start the hub components
        aio.start()
        vad.start()
        asr.start()
        slu.start()
        dm.start()
        nlg.start()
        tts.start()

        # init the system
        call_start = 0
        call_back_time = -1
        call_back_uri = None

        s_voice_activity = False
        s_last_voice_activity_time = 0
        u_voice_activity = False
        u_last_voice_activity_time = 0

        s_last_dm_activity_time = 0

        hangup = False

        call_start = time.time()

        while 1:
            time.sleep(self.cfg['Hub']['main_loop_sleep_time'])

            if call_back_time != -1 and call_back_time < time.time():
                aio_commands.send(Command('make_call(destination="%s")' % \
                                          call_back_uri, 'HUB', 'AIO'))
                call_back_time = -1
                call_back_uri = None

            if vad_commands.poll():
                command = vad_commands.recv()
                self.cfg['Logging']['system_logger'].info(command)

                if isinstance(command, Command):
                    if command.parsed['__name__'] == "speech_start":
                        u_voice_activity = True
                    if command.parsed['__name__'] == "speech_end":
                        u_voice_activity = False
                        u_last_voice_activity_time = time.time()

            if asr_commands.poll():
                command = asr_commands.recv()
                self.cfg['Logging']['system_logger'].info(command)

            if slu_commands.poll():
                command = slu_commands.recv()
                self.cfg['Logging']['system_logger'].info(command)

            if dm_commands.poll():
                command = dm_commands.recv()
                self.cfg['Logging']['system_logger'].info(command)

                if isinstance(command, Command):
                    if command.parsed['__name__'] == "hangup":
                        # prepare for ending the call
                        hangup = True

                    if command.parsed['__name__'] == "dm_da_generated":
                        # record the time of the last system generated dialogue act
                        s_last_dm_activity_time = time.time()

            if nlg_commands.poll():
                command = nlg_commands.recv()
                self.cfg['Logging']['system_logger'].info(command)

            if tts_commands.poll():
                command = tts_commands.recv()
                self.cfg['Logging']['system_logger'].info(command)

            current_time = time.time()

        # stop processes
        aio_commands.send(Command('stop()', 'HUB', 'AIO'))
        vad_commands.send(Command('stop()', 'HUB', 'VAD'))
        asr_commands.send(Command('stop()', 'HUB', 'ASR'))
        slu_commands.send(Command('stop()', 'HUB', 'SLU'))
        dm_commands.send(Command('stop()', 'HUB', 'DM'))
        nlg_commands.send(Command('stop()', 'HUB', 'NLG'))
        tts_commands.send(Command('stop()', 'HUB', 'TTS'))

        # clean connections
        for c in command_connections:
            while c.poll():
                c.recv()

        for c in non_command_connections:
            while c.poll():
                c.recv()

        # wait for processes to stop
        aio.join()
        vad.join()
        tts.join()


def main():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""
        AudioHub runs the spoken dialog system, using your microphone and speakers.

        The default configuration is loaded from '<app root>/resources/default.cfg'.

        Additional configuration parameters can be passed as an argument '-c'.
        Any additional config parameters overwrite their previous values.
      """)

    parser.add_argument('-c', action="append", dest="configs",
        help='additional configuration file')
    args = parser.parse_args()

    cfg = Config('resources/default.cfg', True)

    if args.configs:
        for c in args.configs:
            cfg.merge(c)
    cfg['Logging']['system_logger'].info('config = ' + str(cfg))
    cfg['Logging']['system_logger'].info("Voip Hub\n" + "=" * 120)

    vhub = AudioHub(cfg)
    vhub.run()


if __name__ == '__main__':
    main()
