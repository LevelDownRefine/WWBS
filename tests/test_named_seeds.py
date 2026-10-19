from copy import deepcopy
import unittest
from unittest.mock import patch

from combat_rotation import default_store, new_module
from combat_seed import _export_third_generation, decode_seed, export_seed


def snapshot(preset):
    return {key:preset[key] for key in ('name','slot_order','slot_times')} | {
        'modules':[{key:m[key] for key in ('kind','slot','value','interval')} for m in preset['modules']]}


class NamedSeedTests(unittest.TestCase):
    def test_named_default_is_shorter_including_name_and_identifiers_are_unique(self):
        preset=default_store()['presets'][0]
        seeds=[export_seed(preset) for _ in range(20)]
        self.assertTrue(all(seed.startswith('【默认战斗轴】WWBS4.') for seed in seeds))
        self.assertTrue(all(len(seed)<=90 for seed in seeds))
        self.assertLess(len(seeds[0]),len(_export_third_generation(preset)))
        self.assertEqual(len(set(seeds)),20)
        self.assertEqual(snapshot(decode_seed(seeds[0])),snapshot(preset))

    def test_ten_character_alias_keeps_long_original_preset_name(self):
        preset=default_store()['presets'][0]
        preset['name']='这是已有的完整轴名称，不应被截断'
        alias='一二三四五六七八九十'
        seed=export_seed(preset,seed_name=alias)
        self.assertTrue(seed.startswith('【'+alias+'】WWBS4.'))
        decoded=decode_seed(seed)
        self.assertEqual(decoded['seed_name'],alias)
        self.assertEqual(decoded['name'],preset['name'])

    def test_invalid_alias_is_rejected(self):
        preset=default_store()['presets'][0]
        for alias in ('','   ','一'*11,'【测试】','a\nb'):
            with self.subTest(alias=alias),self.assertRaises(ValueError):
                export_seed(preset,seed_name=alias)

    def test_named_prefix_changes_are_detected_by_checksum(self):
        seed=export_seed(default_store()['presets'][0])
        with self.assertRaisesRegex(ValueError,'校验'):
            decode_seed(seed.replace('默认','其他'))

    def test_original_zero_width_name_is_preserved_and_inserted_chat_formatting_is_tolerated(self):
        preset=default_store()['presets'][0]
        preset['name']='雨\u200b爱'
        seed=export_seed(preset)
        self.assertEqual(snapshot(decode_seed(seed)),snapshot(preset))
        self.assertEqual(snapshot(decode_seed(seed.replace('】WWBS4.','】4.'))),snapshot(preset))
        ordinary=export_seed(default_store()['presets'][0])
        self.assertEqual(decode_seed(ordinary.replace('默认','默\u200b认'))['seed_name'],'默认战斗轴')

    def test_frozen_fourth_generation_defaults_ignore_future_app_defaults(self):
        preset=default_store()['presets'][0]
        seed=export_seed(preset)
        with patch('combat_rotation.default_store') as defaults:
            self.assertEqual(snapshot(decode_seed(seed)),snapshot(preset))
            defaults.assert_not_called()

    def test_old_third_generation_still_decodes_and_reexports_named(self):
        original=default_store()['presets'][0]
        original['slot_order']=[3,2,1]
        index=next(i for i,m in enumerate(original['modules']) if m['slot']==3)
        original['modules'].insert(index,new_module('attack_count',2))
        old=_export_third_generation(original)
        restored=decode_seed(old)
        new=export_seed(restored)
        self.assertEqual(snapshot(decode_seed(new)),snapshot(original))

    def test_arbitrary_numbers_are_lossless(self):
        original=deepcopy(default_store()['presets'][0])
        original['slot_times']={'1':12.345678901,'2':.345678901,'3':19.987654321}
        original['modules'][1]['interval']=8.123456789
        self.assertEqual(snapshot(decode_seed(export_seed(original))),snapshot(original))


if __name__=='__main__':
    unittest.main()
