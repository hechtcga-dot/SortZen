import threading
import unittest

from sortzen.tasks import JobFailed, JobFinished, JobRunner, Progress


class JobRunnerTest(unittest.TestCase):
    def test_result_and_events(self):
        events = []

        def work(emit, token):
            emit(Progress(1, 2))
            return 42

        job = JobRunner().start("count", work, events.append)
        job.join(5)
        self.assertEqual(job.result, 42)
        self.assertEqual(events, [Progress(1, 2), JobFinished("count", 42)])

    def test_failure_is_reported(self):
        events = []

        def work(emit, token):
            raise ValueError("bad folder")

        job = JobRunner().start("scan", work, events.append)
        job.join(5)
        self.assertEqual(events, [JobFailed("scan", "bad folder")])
        self.assertIn("ValueError", job.traceback)

    def test_stop_safely_and_one_job_at_a_time(self):
        started, events = threading.Event(), []

        def work(emit, token):
            started.set()
            token.event.wait(5)
            return "stopped" if token.cancelled else "finished"

        runner = JobRunner()
        job = runner.start("long", work, events.append)
        started.wait(5)
        with self.assertRaises(RuntimeError):
            runner.start("second", work, events.append)
        runner.cancel()
        job.join(5)
        self.assertEqual(job.result, "stopped")
        self.assertFalse(runner.busy)
