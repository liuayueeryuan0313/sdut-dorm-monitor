'use strict';
const $ = id => document.getElementById(id);
let csrf = '', setupRequired = false, snapshot = null, hydrated = false, dirty = false, refreshing = false;
let toastTimer, elcDirty = false;
const elcKeys = ['elc_campus','elc_building','elc_floor','elc_room','elc_type','elc_enabled','elc_minutes'];
function toast(message, error = false) {
  $('toast').textContent = message; $('toast').className = error ? 'error' : ''; $('toast').hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').hidden = true, 5000);
}
async function api(path, payload) {
  const options = {cache: 'no-store', credentials: 'same-origin'};
  if (payload !== undefined) Object.assign(options, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf}, body: JSON.stringify(payload)});
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 401) { $('app').hidden = true; $('auth').hidden = false; hydrated = false; }
    throw new Error(data.error || '请求失败');
  }
  return data;
}
function fillConfig(c) {
  if (!elcDirty) for (const key of elcKeys) { const input = $(key.replace('_', '-')); input[key === 'elc_enabled' ? 'checked' : 'value'] = c[key]; }
  $('sdut-user').value = c.sdut_user; $('qq-appid').value = c.qq_appid;
  $('qq-group').value = c.qq_group_openid; $('push-enabled').checked = c.push_enabled;
  $('poll-minutes').value = c.poll_minutes; $('lookback-days').value = c.lookback_days;
  $('sdut-pwd').value = ''; $('qq-secret').value = '';
  $('notification-provider').value = c.notification_provider;
  $('onebot-url').value = c.onebot_url; $('onebot-group').value = c.onebot_group_id;
  $('onebot-token').value = '';
  $('onebot-token').placeholder = c.onebot_token_set ? '已保存 · 留空保持原令牌' : 'OneBot 访问令牌';
  $('at-all-enabled').checked = Boolean(c.at_all_enabled);
  $('template-dorm').value = c.template_dorm || '';
  $('template-fee').value = c.template_fee || '';
  $('fee-enabled').checked = c.fee_enabled; $('fee-day').value = c.fee_day;
  $('fee-time').value = c.fee_time; $('fee-people').value = c.fee_people; $('fee-amount').value = c.fee_amount;
  $('sdut-pwd').placeholder = c.sdut_pwd_set ? '已保存 · 留空保持原密码' : '输入学校登录密码';
  $('qq-secret').placeholder = c.qq_secret_set ? '已保存 · 留空保持原密钥' : '机器人密钥';
  dirty = false; updatePresets(); updateFeePreview(); updateProvider();
}
function updateProvider() {
  const p = $('notification-provider').value;
  $('onebot-fields').hidden = p !== 'onebot';
  $('official-fields').hidden = p !== 'qq_official';
  $('none-fields').hidden = p !== 'none';
  $('channel-action-row').hidden = p === 'none';
  const checkBtn = $('channel-check') || $('onebot-check');
  if (checkBtn) {
    if (p === 'qq_official') checkBtn.textContent = '验证官方凭据';
    else if (p === 'onebot') checkBtn.textContent = '检查 OneBot 连接';
  }
}
function updateFeePreview() {
  try {
    const raw = $('fee-amount').value, people = Number($('fee-people').value);
    if (!/^\d+(\.\d{1,2})?$/.test(raw) || !Number.isSafeInteger(people) || people < 1 || people > 10000) throw new Error();
    const [units, fraction = ''] = raw.split('.');
    const cents = BigInt(units) * 100n + BigInt(fraction.padEnd(2, '0'));
    if (cents < 1n || cents > 99999999n) throw new Error();
    const fixed = n => String(n / 100n) + '.' + String(n % 100n).padStart(2, '0');
    const total = fixed(cents * BigInt(people)), amount = fixed(cents);
    $('fee-total').textContent = total;
    const monthKey = snapshot?.fee?.month || new Date().toLocaleDateString('sv-SE', {timeZone:'Asia/Shanghai'}).slice(0, 7);
    const [year, month] = monthKey.split('-'); const title = year + '年' + Number(month) + '月';
    const atPrefix = $('at-all-enabled').checked && $('notification-provider').value === 'onebot' ? '@全体成员\n' : '';
    const customTpl = ($('template-fee').value || '').trim();
    if (customTpl) {
      const rendered = customTpl
        .replace(/\{month\}/g, title)
        .replace(/\{people\}/g, String(people))
        .replace(/\{per_person\}/g, amount)
        .replace(/\{total\}/g, total);
      $('fee-preview').textContent = atPrefix + rendered;
    } else {
      $('fee-preview').textContent = atPrefix + '【' + title + '宿舍网费缴纳通知】\n缴费人数：' + people + ' 人\n每人应缴：' + amount + ' 元\n本月合计：' + total + ' 元\n\n请大家前往微信宿舍群转账，每人转账 ' + amount + ' 元，并备注姓名和' + title + '网费。';
    }
  } catch { $('fee-total').textContent = '—'; $('fee-preview').textContent = '请填写有效的缴费人数和金额（最多两位小数）。'; }
}
function updatePresets() {
  document.querySelectorAll('[data-minutes]').forEach(button => button.classList.toggle('active', Number(button.dataset.minutes) === Number($('poll-minutes').value)));
}
function markDirty() { dirty = true; $('save-state').textContent = '有未保存的更改 · 保存后生效'; updatePresets(); updateFeePreview(); updateProvider(); }
function dateParts(value) {
  if (!value) return ['尚未采集', '等待第一次连接'];
  const date = new Date(value);
  return [date.toLocaleTimeString('zh-CN', {timeZone:'Asia/Shanghai',hour12:false}), date.toLocaleDateString('zh-CN', {timeZone:'Asia/Shanghai'}) + ' · 北京时间'];
}
function renderRecords(records) {
  const fragment = document.createDocumentFragment();
  for (const r of records) {
    const tr = document.createElement('tr');
    const values = [r.JCRQ || '—', [r.SSLMC, r.FJH].filter(Boolean).join(' ') || '—', r.JCLXDM_DISPLAY || '—', r.FS ?? '—', r.DJMC || '—', r.WGXX || '—'];
    values.forEach((value, i) => {
      const td = document.createElement('td');
      if (i === 4) { const span = document.createElement('span'); span.className = r.DJMC === '不合格' ? 'grade bad' : 'grade'; span.textContent = String(value); td.append(span); }
      else td.textContent = String(value);
      tr.append(td);
    }); fragment.append(tr);
  }
  $('record-body').replaceChildren(fragment); $('empty-records').hidden = records.length > 0;
  $('rows-label').textContent = snapshot.record_count;
}
function renderEvents(events) {
  if (!events.length) { const p = document.createElement('p'); p.className = 'muted'; p.textContent = '服务已就绪，等待你的配置。'; $('events').replaceChildren(p); return; }
  const fragment = document.createDocumentFragment();
  for (const event of events.slice(0, 30)) {
    const row = document.createElement('div'); row.className = 'event ' + (event.level === 'error' ? 'error' : '');
    const time = document.createElement('time'); time.textContent = event.time.slice(5, 19).replace('T', ' ');
    const text = document.createElement('span'); text.className = 'event-text'; text.textContent = event.message;
    row.append(time, text); fragment.append(row);
  } $('events').replaceChildren(fragment);
}
function countdown() {
  if (!snapshot) return;
  if (snapshot.busy) { $('countdown').textContent = '正在采集'; $('next-copy').textContent = '请稍候，结果会自动更新'; }
  else if (snapshot.config.enabled && snapshot.next_due) {
    const seconds = Math.max(0, Math.ceil(snapshot.next_due - Date.now() / 1000));
    $('countdown').textContent = Math.floor(seconds / 60) + ':' + String(seconds % 60).padStart(2, '0');
    $('next-copy').textContent = '倒计时 · 每 ' + snapshot.config.poll_minutes + ' 分钟';
  } else { $('countdown').textContent = '等待启动'; $('next-copy').textContent = '开启监测后自动刷新'; }
}
async function refresh() {
  if (refreshing || $('app').hidden) return;
  refreshing = true;
  try {
    snapshot = await api('/api/status'); const c = snapshot.config;
    if (!hydrated) { fillConfig(c); hydrated = true; }
    if (!dirty && !$('qq-group').matches(':focus')) $('qq-group').value = c.qq_group_openid;
    $('record-count').replaceChildren(document.createTextNode(snapshot.record_count), Object.assign(document.createElement('small'), {textContent:' 条'}));
    $('interval-value').replaceChildren(document.createTextNode(c.poll_minutes), Object.assign(document.createElement('small'), {textContent:' 分钟'}));
    const [time, date] = dateParts(snapshot.last_success); $('last-success').textContent = time; $('last-date').textContent = date;
    $('run-badge').textContent = snapshot.busy ? '正在采集' : c.enabled ? '监测运行中' : '监测已停止';
    $('run-badge').className = 'pill ' + (snapshot.busy ? 'busy' : c.enabled ? 'running' : 'neutral');
    $('toggle').textContent = c.enabled ? '■ 停止监测' : '▶ 启动监测'; $('toggle').className = c.enabled ? 'primary stop' : 'primary';
    $('preview').disabled = snapshot.busy; $('preview').textContent = snapshot.busy ? '采集中…' : '↻ 手动采集';
    $('capture').disabled = snapshot.capture_busy; $('capture').textContent = snapshot.capture_busy ? '等待群 @…' : '获取群标识';
    $('school-status').textContent = c.sdut_user && c.sdut_pwd_set ? '已配置' : '待配置'; $('school-status').className = 'mini-status' + (c.sdut_user && c.sdut_pwd_set ? ' ready' : '');
    $('school-secret-note').textContent = c.sdut_pwd_set ? '密码已保存；留空保持原密码，填写可替换。' : '用于读取本人查寝记录。';
    $('last-error').hidden = !snapshot.last_error; $('last-error').textContent = snapshot.last_error;
    $('connection').textContent = '● 服务已连接';
    $('records-copy').textContent = snapshot.fresh_count ? snapshot.fresh_count + ' 条未读记录 · 手动采集不推送；QQ 未启用时保留待推送。' : '手动采集不会发送 QQ 消息，也不会改变已读状态。';
    const fee = snapshot.fee;
    $('fee-state').textContent = fee.busy ? '正在 @全体发送' : !c.fee_enabled ? '提醒已关闭' : fee.status === 'sent' ? '本月已发送' : ['failed','sending'].includes(fee.status) ? '发送失败或结果待确认' : '每月提醒已开启';
    $('fee-next').textContent = !c.fee_enabled ? '开启后独立运行，不依赖查寝监测开关' : fee.next_at ? '下次：' + new Date(fee.next_at).toLocaleString('zh-CN', {timeZone:'Asia/Shanghai',hour12:false}) + ' · 北京时间' : '请先核对群内是否已收到，再决定是否重试';
    $('fee-error').hidden = !fee.error; $('fee-error').textContent = fee.error;
    $('fee-retry').hidden = !c.fee_enabled || fee.busy || !['failed','sending'].includes(fee.status);
    if (!dirty) updateFeePreview();
    const elc = snapshot.electricity || {}, result = elc.result;
    $('elc-query').disabled = !!elc.busy || snapshot.busy;
    $('elc-save').disabled = !!elc.busy;
    $('elc-query').textContent = elc.busy ? '查询中…' : '保存并查询电量';
    $('elc-balance').textContent = result?.remaining_kwh ?? '—';
    $('elc-detail').textContent = result ? (result.page_location || result.room) + ' · ' + new Date(result.checked_at).toLocaleString('zh-CN', {timeZone:'Asia/Shanghai', hour12:false}) + ' · ' + (result.balance_cny == null ? '人民币余额未提供' : '余额 ' + result.balance_cny + ' 元') : '尚无查询结果';
    $('elc-error').hidden = !elc.error; $('elc-error').textContent = elc.error || '';
    $('elc-next').textContent = !c.elc_enabled ? '自动查询已关闭' : elc.busy ? '自动计划已开启 · 正在查询' : elc.next_due ? '下次查询：' + new Date(elc.next_due * 1000).toLocaleString('zh-CN', {timeZone:'Asia/Shanghai', hour12:false}) : '等待查询';
    if (!elcDirty) $('elc-enabled').checked = c.elc_enabled;
    renderRecords(snapshot.records); renderEvents(snapshot.events); countdown();
  } catch (error) { $('connection').textContent = '○ 连接中断'; }
  finally { refreshing = false; }
}
async function action(path, message) {
  try { await api(path, {}); toast(message); await refresh(); } catch (error) { toast(error.message, true); }
}
$('auth-form').addEventListener('submit', async event => {
  event.preventDefault(); $('auth-submit').disabled = true; $('auth-error').textContent = '';
  try {
    const result = await api(setupRequired ? '/api/setup' : '/api/login', {password:$('admin-password').value});
    csrf = result.csrf; $('admin-password').value = ''; $('auth').hidden = true; $('app').hidden = false; hydrated = false; await refresh();
  } catch (error) { $('auth-error').textContent = error.message; }
  finally { $('auth-submit').disabled = false; }
});
$('config-form').addEventListener('input', markDirty);
document.querySelectorAll('[data-minutes]').forEach(button => button.addEventListener('click', () => { $('poll-minutes').value = button.dataset.minutes; markDirty(); }));
$('config-form').addEventListener('submit', async event => {
  event.preventDefault(); $('save').disabled = true;
  try {
    await api('/api/config', {
      sdut_user:$('sdut-user').value, sdut_pwd:$('sdut-pwd').value,
      qq_appid:$('qq-appid').value, qq_secret:$('qq-secret').value, qq_group_openid:$('qq-group').value,
      push_enabled:$('push-enabled').checked, poll_minutes:Number($('poll-minutes').value), lookback_days:Number($('lookback-days').value),
      notification_provider:$('notification-provider').value, onebot_url:$('onebot-url').value, onebot_token:$('onebot-token').value,
      onebot_group_id:$('onebot-group').value, at_all_enabled:$('at-all-enabled').checked,
      template_dorm:$('template-dorm').value, template_fee:$('template-fee').value,
      fee_enabled:$('fee-enabled').checked, fee_day:Number($('fee-day').value), fee_time:$('fee-time').value,
      fee_people:Number($('fee-people').value), fee_amount:$('fee-amount').value
    });
    hydrated = false; await refresh(); $('save-state').textContent = '✓ 配置已保存 · 无需重启服务'; toast('配置已保存，刷新计划已更新');
  } catch (error) { toast(error.message, true); }
  finally { $('save').disabled = false; }
});
$('preview').addEventListener('click', () => dirty ? toast('请先保存配置', true) : action('/api/preview', '已开始手动采集，不发送消息'));
$('toggle').addEventListener('click', () => dirty && !snapshot.config.enabled ? toast('请先保存配置', true) : action(snapshot.config.enabled ? '/api/stop' : '/api/start', snapshot.config.enabled ? '监测已停止' : '监测已启动'));
$('capture').addEventListener('click', () => dirty ? toast('请先保存机器人配置', true) : action('/api/capture-group', '正在连接，请在目标群 @ 机器人'));
const checkBtn = $('channel-check') || $('onebot-check');
if (checkBtn) {
  checkBtn.addEventListener('click', async () => {
    if (dirty) { toast('请先保存群通知配置', true); return; }
    checkBtn.disabled = true;
    try {
      const provider = $('notification-provider').value;
      await api('/api/bot-check', {});
      if (provider === 'qq_official') {
        toast('QQ 官方机器人凭据验证通过，Token 获取成功');
      } else {
        const atAll = $('at-all-enabled').checked;
        toast(atAll ? 'OneBot 连接及 @全体权限检查通过，未发送消息' : 'OneBot 基础连接检查通过，未发送消息');
      }
      await refresh();
    }
    catch (error) { toast(error.message, true); }
    finally { checkBtn.disabled = false; }
  });
}
$('bot-test-send').addEventListener('click', async () => {
  if (dirty) { toast('请先保存群通知配置', true); return; }
  $('bot-test-send').disabled = true;
  try {
    await api('/api/bot-test-send', {});
    toast('测试消息已成功发送至目标群，请前往 QQ 查看');
    await refresh();
  }
  catch (error) { toast(error.message, true); }
  finally { $('bot-test-send').disabled = false; }
});
$('fee-retry').addEventListener('click', () => dirty ? toast('请先保存配置', true) : action('/api/fee-retry', '已按你的确认安排重试，请留意群消息'));
$('logout').addEventListener('click', async () => { await action('/api/logout', '已退出'); location.reload(); });
document.querySelectorAll('.nav-item').forEach(link => link.addEventListener('click', () => { document.querySelectorAll('.nav-item').forEach(item => item.classList.remove('selected')); link.classList.add('selected'); }));
for (let day = 1; day <= 31; day++) { const option = document.createElement('option'); option.value = day; option.textContent = '每月 ' + day + ' 日'; $('fee-day').append(option); }
(async () => {
  try {
    const session = await api('/api/session'); csrf = session.csrf || ''; setupRequired = session.setup_required;
    if (session.authenticated) { $('auth').hidden = true; $('app').hidden = false; await refresh(); }
    else { $('auth-title').textContent = setupRequired ? '创建你的管理空间' : '欢迎回来'; $('auth-copy').textContent = setupRequired ? '首次使用，请设置一个管理密码。之后学校和机器人配置都在网页完成。' : '输入管理密码，继续查看查寝更新。'; $('auth-submit').textContent = setupRequired ? '设置密码并进入 ↗' : '登录控制台 ↗'; }
  } catch (error) { $('auth-error').textContent = '无法连接服务，请刷新重试。'; }
})();
setInterval(refresh, 4000); setInterval(countdown, 1000);

$('electricity-form').addEventListener('input', () => { elcDirty = true; });
async function saveElectricity(query) {
  if (dirty) { toast('请先保存上方学校账号和配置', true); return; }
  if (!$('electricity-form').reportValidity()) return;
  const values = Object.fromEntries(elcKeys.map(key => { const input = $(key.replace('_', '-')); return [key, key === 'elc_enabled' ? input.checked : key === 'elc_minutes' ? Number(input.value) : input.value]; }));
  $('elc-query').disabled = true; $('elc-save').disabled = true;
  try { await api(query ? '/api/electricity' : '/api/electricity-config', values); elcDirty = false; toast(query ? '已开始查询电量' : '电量查询计划已保存'); await refresh(); }
  catch (error) { toast(error.message, true); }
  finally { $('elc-query').disabled = !!snapshot?.electricity?.busy; $('elc-save').disabled = !!snapshot?.electricity?.busy; }
}
$('electricity-form').addEventListener('submit', event => { event.preventDefault(); saveElectricity(true); });
$('elc-save').addEventListener('click', () => saveElectricity(false));
