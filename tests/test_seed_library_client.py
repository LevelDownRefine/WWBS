import io
import json
import unittest
from unittest.mock import Mock
import urllib.error

from combat_rotation import default_store
from combat_seed import export_seed
from seed_library import upload_seed,search_seeds,download_seed


def response(data):
    return io.BytesIO(json.dumps(data,ensure_ascii=False).encode())


class SeedLibraryClientTests(unittest.TestCase):
    def test_upload_sends_seed_only_without_local_configuration(self):
        seed=export_seed(default_store()['presets'][0])
        opened=Mock(return_value=response({'item':{'id':'a'*24,'name':'默认战斗轴'}}))
        upload_seed(seed,opener=opened)
        body=json.loads(opened.call_args.args[0].data)
        self.assertEqual(body,{'seed':seed})
        self.assertEqual(opened.call_args.args[0].method,'POST')

    def test_search_names_are_encoded_and_search_limit_enforced(self):
        opened=Mock(return_value=response({'items':[{'id':'a'*24,'name':'测试&名称'}],'truncated':False}))
        items,truncated=search_seeds('测试&名称',opener=opened)
        self.assertEqual(items[0]['name'],'测试&名称')
        self.assertFalse(truncated)
        self.assertIn('%26',opened.call_args.args[0].full_url)
        with self.assertRaises(ValueError):
            search_seeds('一'*11,opener=opened)

    def test_download_requires_correct_id_valid_seed_and_same_name(self):
        seed=export_seed(default_store()['presets'][0])
        opened=Mock(return_value=response({'item':{'id':'a'*24,'name':'默认战斗轴','seed':seed}}))
        self.assertEqual(download_seed('a'*24,opener=opened),seed)
        for item in ({'id':'b'*24,'name':'默认战斗轴','seed':seed},
                     {'id':'a'*24,'name':'其他名称','seed':seed},
                     {'id':'a'*24,'name':'默认战斗轴','seed':'run a command'}):
            with self.assertRaises(ValueError):
                download_seed('a'*24,opener=Mock(return_value=response({'item':item})))

    def test_network_failure_is_a_user_readable_error(self):
        with self.assertRaisesRegex(RuntimeError,'检查网络'):
            search_seeds(opener=Mock(side_effect=urllib.error.URLError('timeout')))


if __name__=='__main__':
    unittest.main()
