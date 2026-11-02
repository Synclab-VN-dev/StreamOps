"""Owner policy regression; these tests do not provision a GitHub trust boundary."""
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

    def test_no_default_write_token_or_tag_publish(self):
        text=(ROOT/'.github/workflows/main.yml').read_text()
        self.assertNotIn('contents: write',text)
        self.assertNotIn('CI_PUBLISH_TOKEN: ${{ github.token }}',text)
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
