"""目录操作依据客户端与服务端能力，私有资源仍可在应用内访问。"""

import subprocess
from pathlib import Path

import pytest
from flask import Flask

from core.api import views
from core.utils import host_capabilities


ROOT = Path(__file__).resolve().parents[1]


def test_file_manager_policy_handles_mobile_remote_and_narrow_desktop():
    script = """
      import assert from 'node:assert/strict';
      import {canUseSystemFileManager as canOpen} from './static/js/utils/fileManager.js';
      const desktop = {serverSupports:true, hostname:'127.0.0.1',
        userAgent:'Mozilla/5.0 (Windows NT 10.0; Win64; x64)', maxTouchPoints:0};
      globalThis.window = {innerWidth:390};
      assert.equal(canOpen(desktop), true, 'narrow desktop retains its capability');
      for (const hostname of ['localhost','[::1]','127.0.0.2']) {
        assert.equal(canOpen({...desktop,hostname}), true);
      }
      for (const hostname of ['192.168.1.8','example.com','localhost.example.com']) {
        assert.equal(canOpen({...desktop,hostname}), false, 'remote host must not open server windows');
      }
      assert.equal(canOpen({...desktop,serverSupports:false}), false);
      for (const userAgent of ['Android 14; Mobile', 'Android 14; Tablet', 'iPhone', 'iPad']) {
        assert.equal(canOpen({...desktop,userAgent}), false);
      }
      assert.equal(canOpen({...desktop,userAgent:'Macintosh; Intel Mac OS X',maxTouchPoints:5}), false);
      assert.equal(canOpen({...desktop,maxTouchPoints:10}), true, 'touch Windows retains desktop tools');
      assert.equal(canOpen({...desktop,nativePlatform:'android'}), false);
      assert.equal(canOpen({...desktop,nativePlatform:'ios'}), false);
      assert.equal(canOpen(), false, 'missing capability declaration fails closed');
    """
    result = subprocess.run(['node', '--input-type=module', '-e', script], cwd=ROOT,
                            capture_output=True, text=True, encoding='utf-8', timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('supported', [False, True])
def test_initial_page_declares_server_file_manager_capability(monkeypatch, supported):
    monkeypatch.setattr(host_capabilities, 'CAN_OPEN_SYSTEM_FILE_MANAGER', supported)
    app = Flask(__name__, template_folder=str(ROOT / 'templates'))
    app.register_blueprint(views.bp)
    response = app.test_client().get('/')
    assert response.status_code == 200
    assert f'name="can-open-system-file-manager" content="{str(supported).lower()}"' in response.text
