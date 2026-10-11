from pathlib import Path
import subprocess
from html.parser import HTMLParser

from flask import Flask, render_template


def test_card_and_worldbook_render_the_shared_file_update_control():
    root = Path(__file__).resolve().parents[1]
    app = Flask(__name__, template_folder=str(root / 'templates'),
                static_folder=str(root / 'static'))

    class DropzoneParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.zones = []
            self.inputs = {}

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if attrs.get('class') == 'detail-update-dropzone':
                self.zones.append(attrs)
            if tag == 'input' and attrs.get('x-ref') in ('cardUpdateInput', 'file'):
                self.inputs[attrs['x-ref']] = attrs

    with app.test_request_context('/'):
        html = render_template('index.html')
    parser = DropzoneParser()
    parser.feed(html)
    card, worldbook = parser.zones
    assert card['aria-label'] == '文件覆盖升级'
    assert 'triggerCardUpdate()' in card['@click']
    assert 'handleUpdateDrop($event)' in card['@drop.prevent']
    assert parser.inputs['cardUpdateInput']['accept'] == '.png,.json'
    assert parser.inputs['cardUpdateInput']['@change'] == 'handleCardUpdate'
    assert worldbook['aria-label'] == '从文件更新'
    assert 'busy' in worldbook['@click']
    assert 'selectFile($event.dataTransfer.files[0])' in worldbook['@drop.prevent']
    assert parser.inputs['file']['@change'] == 'selectFile($event.target.files[0])'
    assert worldbook[':aria-disabled'] == 'busy'
    # Both rendered controls originate from one template rather than divergent copies.
    for name in ('detail_card.html', 'worldbook_update.html'):
        assert 'components/file_update_dropzone.html' in (root / 'templates/modals' / name).read_text()
    modal = (root / 'templates/modals/worldbook_update.html').read_text()
    assert 'Global' not in modal and 'Resource' not in modal and '内嵌' not in modal


def test_worldbook_update_runtime():
    result = subprocess.run(
        ["node", "tests/worldbook_update_runtime_test.mjs"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
