import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error

from update_manager import download_asset, signal_update_ready


class DownloadTests(unittest.TestCase):
    def asset(self, size=10):
        return {'browser_download_url':'https://github.com/ybpan34-prog/WWBS/releases/download/v1.5.4/wwbs-exe.zip',
                'url':'https://api.github.com/repos/ybpan34-prog/WWBS/releases/assets/123','size':size}

    def test_partial_download_retries_from_clean_file_and_renews_redirect(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'update.zip'
            data=b'PK\x03\x04abcdef'
            opened=Mock(side_effect=[io.BytesIO(data[:6]),io.BytesIO(data)])
            sleep=Mock()
            progress=Mock()
            download_asset(self.asset(),path,version='1.5.4',opener=opened,sleep=sleep,progress=progress)
            self.assertEqual(path.read_bytes(),data)
            self.assertIn('wwbs_update=',opened.call_args_list[0].args[0].full_url)
            self.assertEqual(opened.call_args_list[1].args[0].full_url,self.asset()['url'])
            self.assertEqual(progress.call_args.args,(10,10))

    def test_html_and_failed_network_do_not_reach_install(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'update.zip'
            opened=Mock(side_effect=[urllib.error.URLError('network'),io.BytesIO(b'<html>bad'),io.BytesIO(b'PK\x03\x04abcdef')])
            download_asset(self.asset(),path,version='1.5.4',opener=opened,sleep=Mock())
            self.assertEqual(opened.call_count,3)
            opened=Mock(side_effect=urllib.error.URLError('network'))
            with self.assertRaisesRegex(RuntimeError,'重试3次'):
                download_asset(self.asset(),path,version='1.5.4',opener=opened,sleep=Mock())

    def test_cancel_keeps_original_files_and_stops_before_request(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            old=root/'wwbs.exe'
            old.write_bytes(b'old')
            opener=Mock()
            with self.assertRaises(InterruptedError):
                download_asset(self.asset(),root/'update.zip',version='1.5.4',opener=opener,cancelled=lambda:True)
            opener.assert_not_called()
            self.assertEqual(old.read_bytes(),b'old')

    def test_startup_acknowledgement_accepts_update_work_beside_executable(self):
        import update_manager as manager
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            folder=root/('.wwbs-update-work-'+'a'*32)
            folder.mkdir()
            ready=folder/'ready'
            with patch.object(manager.sys,'frozen',True,create=True), \
                    patch.object(manager.sys,'executable',str(root/'wwbs.exe')), \
                    patch.dict(manager.os.environ,{'WWBS_UPDATE_READY':str(ready),'WWBS_UPDATE_TOKEN':'b'*32}):
                signal_update_ready()
            self.assertEqual(ready.read_text(),'b'*32)


if __name__=='__main__':
    unittest.main()
