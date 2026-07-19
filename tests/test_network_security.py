import unittest
from unittest.mock import patch

import modules.network_security as network_security


class NetworkSecurityTests(unittest.TestCase):
    def test_system_trust_injection_is_idempotent(self):
        original = network_security._INJECTED
        network_security._INJECTED = False
        try:
            with patch("truststore.inject_into_ssl") as inject:
                self.assertTrue(network_security.configure_system_trust_store())
                self.assertTrue(network_security.configure_system_trust_store())
                inject.assert_called_once_with()
        finally:
            network_security._INJECTED = original


if __name__ == "__main__":
    unittest.main()
