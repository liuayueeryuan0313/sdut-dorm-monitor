"""Electricity client tests, including dynamic state refresh and CAS callback restart."""
from email.message import Message
import json
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs

import sdut_electricity as elc
from sdut_login import LoginBlocked


def form(token, *, complete=False):
    return '''<form action="./stu_elc.aspx">
    <input type="hidden" name="__VIEWSTATE" value="%s">
    <input type="hidden" name="__EVENTVALIDATION" value="EV-%s">
    <input type="hidden" name="__VIEWSTATEGENERATOR" value="dynamic-%s">
    <input type="hidden" name="__VIEWSTATEFIELDCOUNT" value="2">
    <input type="hidden" name="__VIEWSTATE1" value="part2-%s">
    <input type="radio" name="RadioButtonList2" value="" checked onclick="__doPostBack('RadioButtonList2$0','')">
    <input type="radio" name="RadioButtonList2" value="空调" onclick="__doPostBack('RadioButtonList2$1','')">
    <input type="radio" name="RadioButtonList1" value="西校区" checked onclick="__doPostBack('RadioButtonList1$0','')">
    <input type="radio" name="RadioButtonList1" value="东校区" onclick="__doPostBack('RadioButtonList1$1','')">
    <select name="DropDownList1" onchange="__doPostBack('DropDownList1','')"><option value="0">请选择楼栋</option><option value="476">26号北楼</option></select>
    <select name="DropDownList2" onchange="__doPostBack('DropDownList2','')"><option value="8">8</option></select>
    <select name="DropDownList3"><option value="25961">北楼26-814照明</option></select>
    <input type="submit" name="btn_submit" value="查 询">
    <input type="submit" name="btn_recharge" value="充值">
    %s</form>''' % (token, token, token, token,
                    '<div>剩余电（水）量</div><span>12.34 kW·h</span><div>房间位置</div><span>西校区照明插座-北楼26-814照明</span><div>注意事项</div><p>每小时更新，未尽事宜请到营业室咨询。</p>' if complete else '')


class Response:
    def __init__(self, html, url=elc.QUERY_URL):
        self.html, self.url = html, url
        self.headers = Message()
        self.headers['Content-Type'] = 'text/html; charset=utf-8'

    def read(self):
        return self.html.encode('utf-8')

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


class FormAndResultTests(unittest.TestCase):
    def test_every_hidden_field_and_split_viewstate_is_preserved(self):
        page = elc.FormPage(form('fresh'))
        self.assertEqual(page.fields['__VIEWSTATE1'], 'part2-fresh')
        self.assertEqual(page.fields['__VIEWSTATEFIELDCOUNT'], '2')
        self.assertNotIn('btn_recharge', page.fields)
        self.assertEqual(page.fields['RadioButtonList2'], '')

    def test_html_encoded_postback_target(self):
        page = elc.FormPage('''<input type="radio" name="RadioButtonList2" value="" onclick="setTimeout(&#39;__doPostBack(\\&#39;RadioButtonList2$0\\&#39;,\\&#39;\\&#39;)&#39;,0)">''')
        self.assertEqual(page.radios['RadioButtonList2'][0]['target'], 'RadioButtonList2$0')

    def test_attribute_order_and_entities(self):
        page = elc.FormPage("<input value='a&amp;b' name='__VIEWSTATE' type='hidden'><select name='x'><option value='1'>A &amp; B</option></select>")
        self.assertEqual(page.hidden['__VIEWSTATE'], 'a&b')
        self.assertEqual(page.options('x')[0]['label'], 'A & B')

    def test_real_site_label_preserves_units_and_missing_yuan(self):
        result = elc.parse_balance(form('result', complete=True))
        self.assertEqual(result['remaining_kwh'], '12.34')
        self.assertIsNone(result['balance_cny'])
        self.assertEqual(result['usage_kwh'], {})
        self.assertIn('26-814', result['page_location'])
        self.assertTrue(result['source_notes'])

    def test_explicit_currency_and_usage_can_be_parsed(self):
        result = elc.parse_balance('<table><tr><td>剩余电量（度）</td><td>0.00</td></tr><tr><td>电费余额</td><td>-2.30元</td></tr><tr><td>本月用电量</td><td>18.50度</td></tr></table>')
        self.assertEqual(result['remaining_kwh'], '0.00')
        self.assertEqual(result['balance_cny'], '-2.30')
        self.assertEqual(result['usage_kwh'], {'本月用电量': '18.50'})

    def test_currency_header_unit(self):
        self.assertEqual(elc.parse_balance('<span>余额（元）：12.30</span>')['balance_cny'], '12.30')

    def test_no_result_is_not_zero(self):
        with self.assertRaises(elc.ResultParseError):
            elc.parse_balance(form('initial'))

    def test_conflicting_balance_values_fail_explicitly(self):
        with self.assertRaises(elc.ResultParseError):
            elc.parse_balance('<p>剩余电量：10</p><p>剩余电量：20</p>')

    def test_scripts_cannot_forge_visible_balance(self):
        with self.assertRaises(elc.ResultParseError):
            elc.parse_balance('<script>var fake="剩余电量：123"</script>')

    def test_building_number_must_not_choose_north_or_south_arbitrarily(self):
        options = [dict(value='475', label='26号南楼'), dict(value='476', label='26号北楼')]
        with self.assertRaises(elc.SelectionError):
            elc.resolve_option(options, '26', 'building')
        self.assertEqual(elc.resolve_option(options, '26号北楼', 'building')['value'], '476')
        self.assertEqual(elc.resolve_option(options, 'id:476', 'building')['label'], '26号北楼')

    def test_numeric_room_with_power_suffix(self):
        self.assertEqual(elc.resolve_option([dict(value='25961', label='北楼26-814照明')], '814', 'room')['value'], '25961')

    def test_numeric_room_is_not_interpreted_as_an_unrelated_internal_id(self):
        with self.assertRaises(elc.SelectionError):
            elc.resolve_option([dict(value='814', label='101室')], '814', 'room')

    def test_unavailable_selection_is_rejected(self):
        with self.assertRaises(elc.SelectionError):
            elc.resolve_option([], 'id:123', 'room')


class TransactionTests(unittest.TestCase):
    def opener(self, responses):
        return Mock(open=Mock(side_effect=responses))

    def journey(self, prefix='s'):
        return [Response(form(prefix+str(i))) for i in range(5)] + [Response(form(prefix+'5', complete=True))]

    def test_cascade_uses_latest_tokens_and_only_query_button(self):
        opener = self.opener(self.journey())
        client = elc.ElectricityClient('user', 'password', opener=opener)
        result = client.query('西校区', '26号北楼', '8', '814')
        self.assertEqual(result.remaining_kwh, '12.34')
        calls = opener.open.call_args_list
        self.assertIsNone(calls[0].args[0].data)
        posted = [parse_qs(call.args[0].data.decode(), keep_blank_values=True) for call in calls[1:]]
        self.assertEqual([p['__EVENTTARGET'][0] for p in posted], ['RadioButtonList2$0','RadioButtonList1$0','DropDownList1','DropDownList2',''])
        self.assertEqual([p['__VIEWSTATE'][0] for p in posted], ['s0','s1','s2','s3','s4'])
        self.assertEqual(posted[-1]['DropDownList3'], ['25961'])
        self.assertEqual(posted[-1]['btn_submit'], ['查 询'])
        self.assertTrue(all('btn_recharge' not in p for p in posted))
        self.assertTrue(all(p['RadioButtonList2'] == [''] for p in posted))

    def test_expired_state_is_reselected_after_cas_using_same_opener(self):
        cas_html = '<input id="pwdEncryptSalt" value="1234567890abcdef"><input name="execution" value="flow">'
        cas_url = 'https://authserver.sdut.edu.cn/authserver/login?service=hq-service'
        first = self.journey('old')[:-1] + [Response(cas_html, cas_url)]
        opener = self.opener(first + self.journey('new'))
        client = elc.ElectricityClient('user', 'password', opener=opener)
        with patch.object(elc, 'post_credentials', return_value=(200, form('callback'), elc.QUERY_URL)) as login:
            result = client.query('西校区', '26号北楼', '8', '814')
        login.assert_called_once()
        self.assertIs(login.call_args.args[0], opener)
        self.assertEqual(login.call_args.args[1], cas_url)
        last_form = parse_qs(opener.open.call_args.args[0].data.decode())
        self.assertEqual(last_form['__VIEWSTATE'], ['new4'])
        self.assertEqual(result.selection_ids['room'], '25961')

    def test_rejected_login_is_never_retried(self):
        cas_html = '<input id="pwdEncryptSalt" value="1234567890abcdef"><input name="execution" value="flow">'
        opener = self.opener([Response(cas_html, 'https://authserver.sdut.edu.cn/authserver/login')])
        client = elc.ElectricityClient('user', 'password', opener=opener)
        with patch.object(elc, 'post_credentials', side_effect=LoginBlocked('captcha')) as login, self.assertRaises(LoginBlocked):
            client.query('西校区', '26号北楼', '8', '814')
        login.assert_called_once()
        opener.open.assert_called_once()

    def test_unsupported_salt_is_not_guessed_or_truncated(self):
        cas = '<input id="pwdEncryptSalt" value="' + 'x'*64 + '"><input name="execution" value="flow">'
        opener = self.opener([Response(cas, 'https://authserver.sdut.edu.cn/authserver/login')])
        with patch.object(elc, 'post_credentials') as login, self.assertRaises(LoginBlocked):
            elc.ElectricityClient('user','password',opener=opener).query('西校区','26号北楼','8','814')
        login.assert_not_called()

    def test_public_option_listing_never_submits_query(self):
        opener = self.opener(self.journey()[:5])
        result = elc.ElectricityClient(opener=opener).list_options('西校区','26号北楼','8')
        self.assertEqual(result['level'], 'room')
        self.assertEqual(result['options'][0]['value'], '25961')
        for call in opener.open.call_args_list:
            self.assertNotIn(b'btn_submit', call.args[0].data or b'')

    def test_foreign_form_action_is_not_posted(self):
        page = form('s').replace('./stu_elc.aspx','https://example.com/collect')
        opener = self.opener([Response(page)])
        with self.assertRaises(elc.ElectricityError):
            elc.ElectricityClient(opener=opener).list_options()
        opener.open.assert_called_once()

    def test_repeated_queries_share_one_cookie_opener(self):
        opener = self.opener(self.journey('a') + self.journey('b'))
        client = elc.ElectricityClient('user','password',opener=opener)
        for _ in range(2):
            client.query('西校区','26号北楼','8','814')
        self.assertEqual(opener.open.call_count, 12)


if __name__ == '__main__':
    unittest.main(verbosity=2)
