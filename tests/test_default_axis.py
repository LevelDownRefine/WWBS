"""The supplied seed defines new installs; edited profiles and old seeds survive."""
from copy import deepcopy
import tempfile
import unittest
from pathlib import Path

from combat_rotation import default_store, _previous_default_store, load_store, save_store, validate_store
from combat_seed import decode_seed

SEED = '【默认战斗轴】WWBS4.AYv-g9l9L0bsvLcDxGNgYJADqmARcmDQYGRhZcShDADWKANg'


def content(preset):
    return {key: preset[key] for key in ('name', 'slot_order', 'slot_times')} | {
        'modules': [{key: m[key] for key in ('kind', 'slot', 'value', 'interval')} for m in preset['modules']]}


class DefaultAxisTests(unittest.TestCase):
    def test_factory_axis_is_exactly_the_supplied_seed(self):
        self.assertEqual(content(default_store()['presets'][0]), content(decode_seed(SEED)))

    def test_only_untouched_previous_default_is_upgraded_and_modes_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'axis.json'
            previous = _previous_default_store()
            custom = deepcopy(previous['presets'][0])
            custom.update(id='custom', name='自己编辑的轴')
            previous['presets'].append(custom)
            previous['modes']['daily'] = 'custom'
            save_store(path, previous)
            migrated = load_store(path)
            self.assertEqual(content(migrated['presets'][0]), content(decode_seed(SEED)))
            self.assertEqual(migrated['presets'][1], validate_store(previous)['presets'][1])
            self.assertEqual(migrated['modes'], previous['modes'])
            for field in ('time', 'module', 'order', 'name'):
                edited = _previous_default_store()
                axis = edited['presets'][0]
                if field == 'time':
                    axis['slot_times']['1'] = 24
                elif field == 'module':
                    axis['modules'][0]['value'] = 21
                elif field == 'order':
                    axis['slot_order'] = [3, 2, 1]
                else:
                    axis['name'] = '我的轴'
                save_store(path, edited)
                self.assertEqual(load_store(path), validate_store(edited))
