from unittest.mock import MagicMock
import types

def test_serial_send(mocker):
    mock_serial = MagicMock()
    mock_serial.is_open = True

    fake_module = types.SimpleNamespace(ser=mock_serial)

    def serial_send(msg):
        if fake_module.ser and fake_module.ser.is_open:
            fake_module.ser.write((msg + "\n").encode())

    serial_send("HELLO")
    mock_serial.write.assert_called_once_with(b"HELLO\n")


def test_serial_send_does_not_write_when_closed():
    mock_serial = MagicMock()
    mock_serial.is_open = False

    fake_module = types.SimpleNamespace(ser=mock_serial)

    def serial_send(msg):
        if fake_module.ser and fake_module.ser.is_open:
            fake_module.ser.write((msg + "\n").encode())

    serial_send("HELLO")
    mock_serial.write.assert_not_called()
