import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.services.st_path_safety import evaluate_st_path_safety


class DummySTClient:
    def __init__(self, st_root: str, st_data_dir: str = ''):
        self.st_root = os.path.normpath(st_root)
        self.st_data_dir = os.path.normpath(st_data_dir or st_root)

    def get_st_subdir(self, resource_type: str):
        user_dir = os.path.join(self.st_root, 'data', 'default-user')
        mapping = {
            'characters': os.path.join(user_dir, 'characters'),
            'chats': os.path.join(user_dir, 'chats'),
            'worlds': os.path.join(user_dir, 'worlds'),
            'presets': os.path.join(user_dir, 'OpenAI Settings'),
            'regex': os.path.join(user_dir, 'regex'),
            'scripts': os.path.join(user_dir, 'scripts'),
            'quick_replies': os.path.join(user_dir, 'QuickReplies'),
        }
        return mapping.get(resource_type)

    def get_user_dir(self):
        return os.path.join(self.st_root, 'data', 'default-user')

    def _normalize_default_user_dir(self, path: str):
        normalized = os.path.normpath(path)
        if os.path.basename(normalized).lower() == 'default-user':
            return normalized
        if os.path.basename(normalized).lower() == 'data':
            return os.path.join(normalized, 'default-user')
        return os.path.join(normalized, 'data', 'default-user')


def _factory(st_root: Path):
    return lambda st_data_dir='': DummySTClient(str(st_root), st_data_dir=st_data_dir)


def test_factory_passes_through_requested_st_data_dir(tmp_path):
    st_root = tmp_path / 'SillyTavern'
    requested_path = st_root / 'data'

    client = _factory(st_root)(st_data_dir=str(requested_path))

    assert client.st_data_dir == os.path.normpath(str(requested_path))


def test_evaluate_st_path_safety_marks_chat_overlap_as_danger(tmp_path):
    st_root = tmp_path / 'SillyTavern'
    chats_dir = st_root / 'data' / 'default-user' / 'chats'
    chats_dir.mkdir(parents=True)

    result = evaluate_st_path_safety(
        {
            'st_data_dir': str(st_root),
            'chats_dir': str(chats_dir),
        },
        base_dir=str(tmp_path),
        st_client_factory=_factory(st_root),
    )

    assert result['risk_level'] == 'danger'
    assert result['risk_summary'] == '检测到 1 个路径与 SillyTavern 目录重叠。'
    assert result['blocked_actions'] == ['sync_all', 'sync_chats']
    assert result['conflicts'] == [
        {
            'field': 'chats_dir',
            'label': '聊天记录路径',
            'manager_path': os.path.normpath(str(chats_dir)),
            'st_path': os.path.normpath(str(chats_dir)),
            'resource_type': 'chats',
            'severity': 'danger',
            'relation': 'same',
            'message': '当前聊天记录路径与 SillyTavern chats 目录重叠，同步聊天时可能覆盖同名聊天目录，因此聊天同步已被禁用。',
        }
    ]


def test_evaluate_st_path_safety_resolves_relative_cards_path_against_base_dir(tmp_path):
    st_root = tmp_path / 'SillyTavern'
    chars_dir = st_root / 'data' / 'default-user' / 'characters'
    chars_dir.mkdir(parents=True)

    result = evaluate_st_path_safety(
        {
            'st_data_dir': str(st_root),
            'cards_dir': os.path.relpath(chars_dir, tmp_path),
        },
        base_dir=str(tmp_path),
        st_client_factory=_factory(st_root),
    )

    assert result['risk_level'] == 'warning'
    assert result['blocked_actions'] == ['sync_all', 'sync_characters']
    assert result['conflicts'][0]['field'] == 'cards_dir'
    assert result['conflicts'][0]['relation'] == 'same'
    assert result['conflicts'][0]['severity'] == 'warning'


def test_evaluate_st_path_safety_warns_for_resources_overlap_but_ignores_compatibility_fields(tmp_path):
    st_root = tmp_path / 'SillyTavern'
    public_dir = st_root / 'public'
    public_dir.mkdir(parents=True)

    result = evaluate_st_path_safety(
        {
            'st_data_dir': str(st_root),
            'resources_dir': str(public_dir),
            'st_openai_preset_dir': str(st_root / 'data' / 'default-user' / 'openai'),
        },
        base_dir=str(tmp_path),
        st_client_factory=_factory(st_root),
    )

    assert result['risk_level'] == 'warning'
    assert result['blocked_actions'] == []
    assert len(result['conflicts']) == 1
    assert result['conflicts'][0]['field'] == 'resources_dir'
    assert result['conflicts'][0]['message'] == '当前资源根目录与 SillyTavern 核心目录重叠，可能导致 ST-Manager 资源与酒馆运行目录混用。'


def test_evaluate_st_path_safety_resolves_st_data_dir_data_to_install_root_for_resources_overlap(tmp_path):
    st_root = tmp_path / 'SillyTavern'
    data_dir = st_root / 'data'
    public_dir = st_root / 'public'
    public_dir.mkdir(parents=True)

    result = evaluate_st_path_safety(
        {
            'st_data_dir': str(data_dir),
            'resources_dir': str(public_dir),
        },
        base_dir=str(tmp_path),
        st_client_factory=_factory(st_root),
    )

    assert result['risk_level'] == 'warning'
    assert result['blocked_actions'] == []
    assert result['conflicts'] == [
        {
            'field': 'resources_dir',
            'label': '资源文件夹路径',
            'manager_path': os.path.normpath(str(public_dir)),
            'st_path': os.path.normpath(str(public_dir)),
            'resource_type': 'resources',
            'severity': 'warning',
            'relation': 'same',
            'message': '当前资源根目录与 SillyTavern 核心目录重叠，可能导致 ST-Manager 资源与酒馆运行目录混用。',
        }
    ]


def test_evaluate_st_path_safety_resolves_default_user_st_data_dir_to_install_root_for_resources_overlap(tmp_path):
    st_root = tmp_path / 'SillyTavern'
    default_user_dir = st_root / 'data' / 'default-user'
    public_dir = st_root / 'public'
    public_dir.mkdir(parents=True)

    result = evaluate_st_path_safety(
        {
            'st_data_dir': str(default_user_dir),
            'resources_dir': str(public_dir),
        },
        base_dir=str(tmp_path),
        st_client_factory=_factory(st_root),
    )

    assert result['risk_level'] == 'warning'
    assert result['blocked_actions'] == []
    assert result['conflicts'] == [
        {
            'field': 'resources_dir',
            'label': '资源文件夹路径',
            'manager_path': os.path.normpath(str(public_dir)),
            'st_path': os.path.normpath(str(public_dir)),
            'resource_type': 'resources',
            'severity': 'warning',
            'relation': 'same',
            'message': '当前资源根目录与 SillyTavern 核心目录重叠，可能导致 ST-Manager 资源与酒馆运行目录混用。',
        }
    ]


def test_evaluate_st_path_safety_marks_manager_inside_st_relation(tmp_path):
    st_root = tmp_path / 'SillyTavern'
    chats_dir = st_root / 'data' / 'default-user' / 'chats'
    nested_dir = chats_dir / 'nested'
    nested_dir.mkdir(parents=True)

    result = evaluate_st_path_safety(
        {
            'st_data_dir': str(st_root),
            'chats_dir': str(nested_dir),
        },
        base_dir=str(tmp_path),
        st_client_factory=_factory(st_root),
    )

    assert result['risk_level'] == 'danger'
    assert result['blocked_actions'] == ['sync_all', 'sync_chats']
    assert result['conflicts'][0]['field'] == 'chats_dir'
    assert result['conflicts'][0]['relation'] == 'manager_inside_st'
    assert result['conflicts'][0]['manager_path'] == os.path.normpath(str(nested_dir))
    assert result['conflicts'][0]['st_path'] == os.path.normpath(str(chats_dir))


def test_evaluate_st_path_safety_uses_user_dir_boundary_for_scripts(tmp_path):
    st_root = tmp_path / 'SillyTavern'
    user_dir = st_root / 'data' / 'default-user'
    scripts_export_dir = user_dir / 'manager-scripts'
    scripts_export_dir.mkdir(parents=True)

    result = evaluate_st_path_safety(
        {
            'st_data_dir': str(st_root),
            'scripts_dir': str(scripts_export_dir),
        },
        base_dir=str(tmp_path),
        st_client_factory=_factory(st_root),
    )

    assert result['risk_level'] == 'warning'
    assert result['blocked_actions'] == ['sync_all', 'sync_scripts']
    assert result['conflicts'][0]['resource_type'] == 'scripts'
    assert result['conflicts'][0]['st_path'] == os.path.normpath(str(user_dir))


def test_evaluate_st_path_safety_marks_st_inside_manager_relation(tmp_path):
    st_root = tmp_path / 'SillyTavern'
    chats_dir = st_root / 'data' / 'default-user' / 'chats'
    chats_dir.mkdir(parents=True)

    result = evaluate_st_path_safety(
        {
            'st_data_dir': str(st_root),
            'chats_dir': str(chats_dir.parent),
        },
        base_dir=str(tmp_path),
        st_client_factory=_factory(st_root),
    )

    assert result['risk_level'] == 'danger'
    assert result['blocked_actions'] == ['sync_all', 'sync_chats']
    assert result['conflicts'][0]['field'] == 'chats_dir'
    assert result['conflicts'][0]['relation'] == 'st_inside_manager'
    assert result['conflicts'][0]['manager_path'] == os.path.normpath(str(chats_dir.parent))
    assert result['conflicts'][0]['st_path'] == os.path.normpath(str(chats_dir))


def test_path_safety_only_reports_openai_preset_directory_for_preset_conflicts(tmp_path):
    st_root = tmp_path / 'SillyTavern'
    st_presets_dir = st_root / 'data' / 'default-user' / 'OpenAI Settings'
    st_presets_dir.mkdir(parents=True)

    result = evaluate_st_path_safety(
        {
            'st_data_dir': str(st_root / 'data' / 'default-user'),
            'presets_dir': str(st_presets_dir),
            'st_openai_preset_dir': str(st_root / 'data' / 'default-user' / 'openai'),
        },
        base_dir=str(tmp_path),
        st_client_factory=_factory(st_root),
    )

    fields = {item['field'] for item in result['conflicts']}
    assert 'presets_dir' in fields
    assert 'st_openai_preset_dir' not in fields
    assert 'st_textgen_preset_dir' not in fields
    assert 'st_instruct_preset_dir' not in fields
    assert 'st_context_preset_dir' not in fields
    assert 'st_sysprompt_dir' not in fields
    assert 'st_reasoning_dir' not in fields
