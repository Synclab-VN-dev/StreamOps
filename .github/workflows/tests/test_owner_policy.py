"""Intended-flow policy; malicious write collaborators are outside the threat model."""
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from test_ci import ci

ROOT = Path(__file__).resolve().parents[3]

class OwnerPolicy(unittest.TestCase):
    def test_triggers(self):
        text=(ROOT/'.github/workflows/main.yml').read_text()
        triggers=text.split("'on':\n",1)[1].split('permissions:',1)[0]
        self.assertIn('  push:\n    branches: [master]\n',triggers)
        self.assertIn('  pull_request: null\n',triggers)
        self.assertIn('  workflow_dispatch:',triggers)
        self.assertNotIn('tags:',triggers)

    def test_write_token_is_scoped_to_manual_master_publish(self):
        text=(ROOT/'.github/workflows/main.yml').read_text()
        publish=text.split('\n  publish:',1)[1].split('\n  external_publish:',1)[0]
        others=text.replace(publish,'')
        self.assertIn('permissions:\n      contents: write',publish)
        self.assertIn('CI_PUBLISH_TOKEN: ${{ github.token }}',publish)
        self.assertNotIn('contents: write',others)
        self.assertNotIn('CI_PUBLISH_TOKEN:',others)
        for condition in ("github.event_name == 'workflow_dispatch'", "inputs.operation == 'publish'", "github.ref == 'refs/heads/master'"):
            self.assertIn(condition,publish.split('strategy:',1)[0])
        self.assertNotIn('environment:',publish)
        self.assertNotIn('CI_PRODUCTION_RELEASE_TOKEN',text)
        self.assertNotIn("startsWith(github.ref, 'refs/tags/')",text)

    def test_optional_jobs_rejected(self):
        for value in (False,True):
            text="CI_SPEC = "+repr(dict(version=1,id='widget',jobs=[dict(id='unit',profile='linux',timeout=1,required=value)]))+"\ndef run(ctx): pass\n"
            with self.assertRaisesRegex(ci.ContractError,'UNKNOWN_JOB_FIELD'):
                ci.metadata(text,'widget/ci.test.py')

    def test_no_legacy_channel_or_tag_metadata(self):
        for name in ('.github/workflows/ci.py','utility/d4planner/ci.release.py','utility/d4planner/d4planner-be/tools/release_ci.py'):
            text=(ROOT/name).read_text()
            for legacy in ('publish-uat','release_tags','ctx.channel','uat_tag'):
                self.assertNotIn(legacy,text)

if __name__=='__main__':unittest.main()
