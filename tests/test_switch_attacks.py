import threading
import time
import unittest
from unittest.mock import Mock

import app
from combat_rotation import IdleAttackWorker


class Controller:
    def __init__(self):
        self.slot=1
        self.clicks=[]
        self.press_key=Mock(side_effect=self.switch)
        self.release_keys=Mock()
        self.hold_left_button=Mock()
    def switch(self,key,_duration):
        self.slot=int(key)
    def active_character_slot(self,_path):
        return self.slot
    def left_click(self):
        self.clicks.append(time.monotonic())


class SwitchAttackTests(unittest.TestCase):
    def test_slow_confirmation_keeps_clicking_and_all_exit_paths_pause_the_worker(self):
        for outcome in ('confirmed','stopped','settlement','error'):
            with self.subTest(outcome=outcome):
                controller=Controller()
                runner=app.TaskRunner(controller,Mock(),dry_run=False)
                runner._rotation_slot=1
                runner._sleep_interruptible=lambda seconds: runner.stop_event.wait(seconds)
                worker=IdleAttackWorker(controller,runner.stop_event,threading.Lock(),attack_interval=.025)
                runner._rotation_idle_worker=worker
                frames=[]
                def capture(_):
                    if controller.slot==2:
                        start=time.monotonic()
                        time.sleep(.18)
                        frames.append((start,time.monotonic()))
                        if outcome=='stopped':
                            runner.stop_event.set()
                        if outcome=='settlement':
                            runner._rotation_battle_finished=True
                        if outcome=='error':
                            raise RuntimeError('capture failed')
                runner._capture_for_matching=capture
                try:
                    if outcome=='error':
                        with self.assertRaisesRegex(RuntimeError,'capture failed'):
                            runner._select_rotation_slot(2,verify=True)
                    else:
                        self.assertEqual(runner._select_rotation_slot(2,verify=True),outcome=='confirmed')
                    self.assertTrue(frames)
                    self.assertGreaterEqual(sum(frames[0][0] < stamp < frames[0][1] for stamp in controller.clicks),3)
                    count=len(controller.clicks)
                    time.sleep(.08)
                    self.assertEqual(len(controller.clicks),count)
                    controller.hold_left_button.assert_not_called()
                finally:
                    worker.close()


if __name__=='__main__':
    unittest.main()
