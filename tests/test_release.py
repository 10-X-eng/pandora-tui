import importlib.util
from pathlib import Path

path=Path(__file__).parents[1]/'scripts/audit_release.py'
spec=importlib.util.spec_from_file_location('release_audit',path)
audit=importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_audit_rejects_external_private_values_without_echoing_them():
    assert audit.inspect('sample.py',b'fixture-secret',[b'fixture-secret'])==['private value']
    assert audit.inspect('sample.py',b'you@example.com',[])==[]
    # Construct fixtures so their literal private examples are not release data.
    address=b'person@'+b'private'+b'.test'
    assert 'non-example email' in audit.inspect('sample.py',address,[])
    home=b'/'+b'home/'+b'fixture'
    assert 'personal home path' in audit.inspect('sample.py',home,[])
