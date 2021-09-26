from absl.testing import absltest
from absl import logging


class HelloTest(absltest.TestCase):
    def test_hello(self):
        self.assertEqual(2, 1 + 1)
        logging.info("hello test OK")


if __name__ == '__main__':
    absltest.main()
