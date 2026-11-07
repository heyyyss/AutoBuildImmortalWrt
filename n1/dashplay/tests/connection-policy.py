import importlib.util
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

spec=importlib.util.spec_from_file_location('policy',Path(__file__).resolve().parents[1]/'support/usr/libexec/n1-connection-policy.py')
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
O=m.Observation

class PolicyTest(unittest.TestCase):
    def loss(self,old='wireless',usb=True,wifi=True):
        p=m.Policy();p.observe(O(old,usb,wifi),0)
        self.assertIsNone(p.observe(O(None,usb,wifi),1))
        return p,p.observe(O(None,usb,wifi),5)
    def test_live_never_preempted(self):
        for route in ['wired','wireless']:
            p=m.Policy()
            for t in range(100):
                self.assertIsNone(p.observe(O(route,t%2==0,t%3==0),t))
                self.assertEqual(p.phase,'healthy_'+route)
    def test_wireless_loss_even_when_still_associated(self):
        p,a=self.loss();self.assertEqual(a.target,'wired')
    def test_wired_loss(self):
        p,a=self.loss('wired',False,True);self.assertIsNone(a)
        self.assertEqual(p.observe(O(None,False,True),20).target,'wireless')
    def test_both_down_each_return(self):
        for target in ['wired','wireless']:
            p=m.Policy();p.observe(O('wireless',True,True),0)
            self.assertIsNone(p.observe(O(None,False,False),1))
            self.assertIsNone(p.observe(O(None,False,False),60))
            a=p.observe(O(None,target=='wired',target=='wireless'),61)
            if target=='wireless':
                self.assertIsNone(a)
                a=p.observe(O(None,False,True),81)
            self.assertEqual(a.target,target)
    def test_attempt_has_time_to_finish(self):
        p,a=self.loss()
        for t in range(6,35):self.assertIsNone(p.observe(O(None,True,True),t))
        self.assertEqual(p.observe(O(None,True,True),35).target,'wireless')
    def test_failed_route_alternates(self):
        p,a=self.loss();p.rejected(5)
        self.assertIsNone(p.observe(O(None,True,True),7))
        self.assertEqual(p.observe(O(None,True,True),20).target,'wireless')
    def test_only_route_retries_with_backoff(self):
        p,a=self.loss('wireless',True,False);p.rejected(5)
        self.assertIsNone(p.observe(O(None,True,False),10))
        self.assertEqual(p.observe(O(None,True,False),15).target,'wired')
        p.rejected(15)
        self.assertIsNone(p.observe(O(None,True,False),34))
        self.assertEqual(p.observe(O(None,True,False),35).target,'wired')
    def test_restored_link_bypasses_backoff(self):
        p,a=self.loss('wireless',True,False);p.rejected(5)
        p.observe(O(None,False,False),6)
        self.assertEqual(p.observe(O(None,True,False),7).target,'wired')
    def test_display_grace(self):
        p=m.Policy();p.observe(O('wireless',True,True),0)
        p.observe(O(None,True,True,display_changed=True),1)
        self.assertIsNone(p.observe(O(None,True,True),30))
        self.assertEqual(p.observe(O(None,True,True),31).target,'wired')
    def test_physical_loss_overrides_display_grace(self):
        p=m.Policy();p.observe(O('wireless',True,True),0)
        p.observe(O(None,True,False,display_changed=True),1)
        self.assertEqual(p.observe(O(None,True,False),5).target,'wired')
    def test_static_disable_and_unknown_wifi(self):
        p=m.Policy();p.observe(O(None,True,None,allowed_usb=False),0)
        self.assertIsNone(p.observe(O(None,True,None,allowed_usb=False),100))
        self.assertEqual(p.phase,'waiting_link')
    def test_multiple_phones_need_explicit_selection(self):
        p=m.Policy();p.observe(O(None,True,True,automatic=False),0)
        self.assertIsNone(p.observe(O(None,True,True,automatic=False),100))
        self.assertEqual(p.phase,'manual_selection_required')
    def test_native_wireless_recovery_wins_during_grace(self):
        p,a=self.loss('wired',False,True)
        self.assertIsNone(a)
        self.assertIsNone(p.observe(O('wireless',False,True),8))
        self.assertEqual(p.phase,'healthy_wireless')
        self.assertIsNone(p.pending)
    def test_native_progress_defers_reinvitation(self):
        p,a=self.loss('wired',False,True)
        self.assertIsNone(p.observe(O(None,False,True,native_progress=True),25))
        self.assertEqual(p.phase,'waiting_native_wireless')
        self.assertEqual(p.observe(O(None,False,True),40).target,'wireless')
    def test_last_moment_native_progress_does_not_post(self):
        p=m.Policy();p.pending='wireless'
        from unittest.mock import Mock
        events=Mock(native_until=float('inf'))
        rows={'phones':[{'address':'00:11:22:33:44:55'}]}
        with patch.object(m,'api',return_value=rows) as api, patch.object(m,'wifi_present',return_value=True):
            m.perform(m.Action('wireless','test'),p,events)
            api.assert_called_once_with('/api/phones')
        self.assertIsNone(p.pending)
    def test_recovered_session_wins_at_mutation(self):
        p,a=self.loss()
        with patch.object(m,'api',return_value={'wired':'live'}) as api:
            m.perform(a,p)
            api.assert_called_once_with('/api/phones')
    def test_perform_posts_correct_route(self):
        for target in ['wired','wireless']:
            p=m.Policy();p.pending=target
            rows={'phones':[{'address':'00:11:22:33:44:55'}]}
            with patch.object(m,'api',side_effect=[rows,{'ok':True}]) as api, patch.object(m,'usb_present',return_value=True), patch.object(m,'wifi_present',return_value=True), patch.object(m,'read',return_value='once'),patch.object(m,'event'):
                m.perform(m.Action(target,'test'),p)
                expected={'cable':True} if target=='wired' else {'address':'00:11:22:33:44:55'}
                self.assertEqual(api.call_args.args,('/api/phones/switch',expected))

if __name__=='__main__':unittest.main(verbosity=2)
