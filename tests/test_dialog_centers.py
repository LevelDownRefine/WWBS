import tkinter as tk
import unittest
from unittest.mock import patch

import app
from ui_controls import RoundedButton


class DialogCenterTests(unittest.TestCase):
    def test_custom_four_c_count_opens_at_owner_center_and_cancel_keeps_value(self):
        root=tk.Tk()
        try:
            root.geometry('1050x820+200+60')
            root.update()
            ui=app.App.__new__(app.App)
            ui.root=root
            results=[]
            def inspect():
                window=next(w for w in root.winfo_children() if isinstance(w,tk.Toplevel))
                window.update_idletasks()
                def walk(widget):
                    yield widget
                    for child in widget.winfo_children():
                        yield from walk(child)
                buttons=[w for w in walk(window) if isinstance(w,RoundedButton) or (
                    isinstance(w,tk.Canvas) and any(w.type(item)=='text' and w.itemcget(item,'text') in ('确定','取消')
                                                   for item in w.find_all()))]
                visibility=[(button.winfo_ismapped(),button.winfo_rooty()+button.winfo_height() <=
                             window.winfo_rooty()+window.winfo_height()) for button in buttons]
                results.append((abs(window.winfo_rootx()+window.winfo_width()/2-root.winfo_rootx()-root.winfo_width()/2),
                                abs(window.winfo_rooty()+window.winfo_height()/2-root.winfo_rooty()-root.winfo_height()/2),visibility))
                window.destroy()
            root.after(500,inspect)
            self.assertIsNone(ui._ask_4c_count(42))
            self.assertEqual(len(results),1)
            self.assertLess(results[0][0],40)
            self.assertLess(results[0][1],40)
            self.assertEqual(len(results[0][2]),2)
            self.assertTrue(all(mapped and fits for mapped,fits in results[0][2]))
        finally:
            root.destroy()

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
