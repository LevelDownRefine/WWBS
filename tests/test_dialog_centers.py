import tkinter as tk
import unittest
from unittest.mock import patch


class DialogCenterTests(unittest.TestCase):
    def test_native_dialogs_receive_main_owner_when_not_explicitly_parented(self):
        from ui_controls import ParentDialogs
        from unittest.mock import Mock
        module=Mock()
        owner=object()
        wrapper=ParentDialogs(module)
        with patch.object(tk,'_default_root',owner):
            wrapper.showinfo('标题','内容')
        module.showinfo.assert_called_once_with('标题','内容',parent=owner)


if __name__=='__main__':
    unittest.main()
