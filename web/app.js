'use strict';
const $ = id => document.getElementById(id);
let csrf = '', setupRequired = false, snapshot = null, hydrated = false, dirty = false, refreshing = false;
let toastTimer, elcDirty = false, currentLogFilter = 'all';
const elcKeys = ['elc_campus','elc_building','elc_floor','elc_room','elc_type','elc_enabled','elc_warn_thresholds'];

function toast(message, error = false) {
  $('toast').textContent = message;
  $('toast').className = error ? 'error' : '';
  $('toast').hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $('toast').hidden = true, 5000);
}

async function api(path, payload) {
  const options = {cache: 'no-store', credentials: 'same-origin'};
  if (payload !== undefined) {
    Object.assign(options, {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf},
      body: JSON.stringify(payload)
    });
  }
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 401) {
      $('app').hidden = true;
      $('auth').hidden = false;
      hydrated = false;
    }
    throw new Error(data.error || '请求失败');
  }
  return data;
}

function switchView(target) {
  const allowed = ['overview', 'configuration', 'records', 'electricity', 'activity'];
  const viewId = allowed.includes(target) ? target : 'overview';

  document.querySelectorAll('.nav-item').forEach(item => {
    const itemTarget = item.dataset.target || (item.getAttribute('href') || '').replace('#', '');
    item.classList.toggle('selected', itemTarget === viewId);
  });

  document.querySelectorAll('.view-panel').forEach(panel => {
    const isTarget = panel.id === 'view-' + viewId;
    panel.hidden = !isTarget;
    panel.classList.toggle('active', isTarget);
  });

  if (location.hash !== '#' + viewId) {
    history.replaceState(null, '', '#' + viewId);
  }
}

function fillConfig(c) {
  if (!elcDirty) {
    for (const key of elcKeys) {
      const input = $(key.replace('_', '-'));
      if (input) {
        input[key === 'elc_enabled' ? 'checked' : 'value'] = c[key] !== undefined ? c[key] : (key === 'elc_warn_thresholds' ? '50, 20, 10, 5' : '');
      }
    }
  }
  $('sdut-user').value = c.sdut_user || '';
  $('qq-appid').value = c.qq_appid || '';
  $('qq-group').value = c.qq_group_openid || '';
  $('push-enabled').checked = Boolean(c.push_enabled);
  $('poll-minutes').value = c.poll_minutes;
  $('lookback-days').value = c.lookback_days;
  $('sdut-pwd').value = '';
  $('qq-secret').value = '';
  $('notification-provider').value = c.notification_provider || 'onebot';
  $('onebot-url').value = c.onebot_url || '';
  $('onebot-group').value = c.onebot_group_id || '';
  $('onebot-token').value = '';
  $('onebot-token').placeholder = c.onebot_token_set ? '已保存 · 留空保持原令牌' : 'OneBot 访问令牌';
  $('at-all-enabled').checked = Boolean(c.at_all_enabled);
  $('template-dorm').value = c.template_dorm || '';
  $('template-fee').value = c.template_fee || '';
  $('template-elc').value = c.template_elc || '';
  $('fee-enabled').checked = Boolean(c.fee_enabled);
  $('fee-day').value = c.fee_day || 1;
  $('fee-time').value = c.fee_time || '09:00';
  $('fee-people').value = c.fee_people || 4;
  $('fee-amount').value = c.fee_amount || '20.00';
  $('sdut-pwd').placeholder = c.sdut_pwd_set ? '已保存 · 留空保持原密码' : '输入学校登录密码';
  $('qq-secret').placeholder = c.qq_secret_set ? '已保存 · 留空保持原密钥' : '机器人密钥';
  dirty = false;
  updatePresets();
  updateFeePreview();
  updateProvider();
}

function updateProvider() {
  const p = $('notification-provider').value;
  $('onebot-fields').hidden = p !== 'onebot';
  $('official-fields').hidden = p !== 'qq_official';
  $('none-fields').hidden = p !== 'none';
  $('channel-action-row').hidden = p === 'none';
  const checkBtn = $('channel-check');
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
    const [year, month] = monthKey.split('-');
    const title = year + '年' + Number(month) + '月';
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
  } catch {
    $('fee-total').textContent = '—';
    $('fee-preview').textContent = '请填写有效的缴费人数和金额（最多两位小数）。';
  }
}

function updatePresets() {
  document.querySelectorAll('[data-minutes]').forEach(button => {
    button.classList.toggle('active', Number(button.dataset.minutes) === Number($('poll-minutes').value));
  });
}

function markDirty() {
  dirty = true;
  $('save-state').textContent = '有未保存的更改 · 保存后生效';
  updatePresets();
  updateFeePreview();
  updateProvider();
}

function dateParts(value) {
  if (!value) return ['尚未采集', '等待第一次连接'];
  const date = new Date(value);
  return [
    date.toLocaleTimeString('zh-CN', {timeZone:'Asia/Shanghai', hour12:false}),
    date.toLocaleDateString('zh-CN', {timeZone:'Asia/Shanghai'}) + ' · 北京时间'
  ];
}

function renderRecords(records) {
  const fragment = document.createDocumentFragment();
  for (const r of records) {
    const tr = document.createElement('tr');
    const values = [
      r.JCRQ || '—',
      [r.SSLMC, r.FJH].filter(Boolean).join(' ') || '—',
      r.JCLXDM_DISPLAY || '—',
      r.FS ?? '—',
      r.DJMC || '—',
      r.WGXX || '—'
    ];
    values.forEach((value, i) => {
      const td = document.createElement('td');
      if (i === 4) {
        const span = document.createElement('span');
        span.className = r.DJMC === '不合格' ? 'grade bad' : 'grade';
        span.textContent = String(value);
        td.append(span);
      } else {
        td.textContent = String(value);
      }
      tr.append(td);
    });
    fragment.append(tr);
  }
  $('record-body').replaceChildren(fragment);
  $('empty-records').hidden = records.length > 0;
  $('rows-label').textContent = snapshot ? snapshot.record_count : '0';

  // Overview quick records preview
  const prevBox = $('overview-records-preview');
  if (prevBox) {
    if (!records.length) {
      prevBox.innerHTML = '<p class="muted" style="font-size:12px;padding:12px 0;">暂无查寝记录，请先在「连接与计划」配置学校账号并执行采集。</p>';
    } else {
      const pFrag = document.createDocumentFragment();
      for (const r of records.slice(0, 3)) {
        const item = document.createElement('div');
        item.style.cssText = 'display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.05);font-size:12px;';
        const left = document.createElement('div');
        left.innerHTML = `<strong>${r.JCRQ || ''}</strong> <span class="muted" style="margin-left:6px;">${r.SSLMC || ''} ${r.FJH || ''}</span>`;
        const right = document.createElement('div');
        const badge = document.createElement('span');
        badge.className = r.DJMC === '不合格' ? 'grade bad' : 'grade';
        badge.textContent = `${r.FS ?? '—'} 分 (${r.DJMC || '合格'})`;
        right.appendChild(badge);
        item.append(left, right);
        pFrag.append(item);
      }
      prevBox.replaceChildren(pFrag);
    }
  }
}

function renderEvents() {
  const events = (snapshot?.logs || snapshot?.events || []);
  const filtered = events.filter(e => {
    if (currentLogFilter === 'all') return true;
    if (currentLogFilter === 'error') return e.level === 'error';
    return e.category === currentLogFilter;
  });

  if (!filtered.length) {
    const p = document.createElement('p');
    p.className = 'muted';
    p.textContent = currentLogFilter === 'all' ? '服务已就绪，暂无运行日志。' : '当前分类暂无日志记录。';
    $('events').replaceChildren(p);
  } else {
    const fragment = document.createDocumentFragment();
    for (const event of filtered.slice(0, 150)) {
      const row = document.createElement('div');
      row.className = 'log-entry ' + (event.level === 'error' ? 'error' : '');
      const time = document.createElement('time');
      time.className = 'log-time';
      time.textContent = (event.time || '').slice(5, 19).replace('T', ' ');

      const badge = document.createElement('span');
      badge.className = 'log-badge ' + (event.category || 'system');
      const catNames = {auth:'认证', dorm:'查寝', electricity:'电量', bot:'推送', system:'系统'};
      badge.textContent = catNames[event.category] || event.category || '动态';

      const level = document.createElement('span');
      level.className = 'log-level ' + (event.level || 'info');
      level.textContent = (event.level || 'info').toUpperCase();

      const text = document.createElement('span');
      text.className = 'log-msg ' + (event.level === 'error' ? 'error' : '');
      text.textContent = event.message;

      row.append(time, badge, level, text);
      fragment.append(row);
    }
    $('events').replaceChildren(fragment);
  }

  // Overview quick events preview
  const prevBox = $('overview-events-preview');
  if (prevBox) {
    if (!events.length) {
      prevBox.innerHTML = '<p class="muted">服务已就绪，正在等待任务调度...</p>';
    } else {
      const pFrag = document.createDocumentFragment();
      for (const ev of events.slice(0, 4)) {
        const item = document.createElement('div');
        item.style.cssText = 'display:flex;align-items:baseline;gap:6px;';
        const t = document.createElement('span');
        t.style.cssText = 'color:var(--text-dim);font-size:10.5px;';
        t.textContent = (ev.time || '').slice(11, 19);
        const m = document.createElement('span');
        m.style.cssText = ev.level === 'error' ? 'color:#fda4af;' : 'color:var(--text-main);';
        m.textContent = ev.message;
        item.append(t, m);
        pFrag.append(item);
      }
      prevBox.replaceChildren(pFrag);
    }
  }
}

function countdown() {
  if (!snapshot) return;
  if (snapshot.busy) {
    $('countdown').textContent = '正在采集';
    $('next-copy').textContent = '请稍候，查寝与电量正在采集更新';
  } else if (snapshot.config.enabled && snapshot.next_due) {
    const seconds = Math.max(0, Math.ceil(snapshot.next_due - Date.now() / 1000));
    $('countdown').textContent = Math.floor(seconds / 60) + ':' + String(seconds % 60).padStart(2, '0');
    $('next-copy').textContent = '倒计时 · 每 ' + snapshot.config.poll_minutes + ' 分钟';
  } else {
    $('countdown').textContent = '等待启动';
    $('next-copy').textContent = '开启监测后自动定时采集';
  }
}

async function refresh() {
  if (refreshing || $('app').hidden) return;
  refreshing = true;
  try {
    snapshot = await api('/api/status');
    const c = snapshot.config;
    if (!hydrated) {
      fillConfig(c);
      hydrated = true;
    }
    if (!dirty && !$('qq-group').matches(':focus')) {
      $('qq-group').value = c.qq_group_openid;
    }
    $('record-count').replaceChildren(document.createTextNode(snapshot.record_count), Object.assign(document.createElement('small'), {textContent:' 条'}));
    $('interval-value').replaceChildren(document.createTextNode(c.poll_minutes), Object.assign(document.createElement('small'), {textContent:' 分钟'}));
    const [time, date] = dateParts(snapshot.last_success);
    $('last-date').textContent = snapshot.last_success ? '最近采集: ' + time : '尚未采集';
    $('run-badge').textContent = snapshot.busy ? '正在采集' : c.enabled ? '监测运行中' : '监测已停止';
    $('run-badge').className = 'pill ' + (snapshot.busy ? 'busy' : c.enabled ? 'running' : 'neutral');
    $('toggle').textContent = c.enabled ? '■ 停止监测' : '▶ 启动监测';
    $('toggle').className = c.enabled ? 'primary stop' : 'primary';
    if ($('overview-toggle')) {
      $('overview-toggle').textContent = c.enabled ? '■ 停止监测' : '▶ 启动监测';
      $('overview-toggle').className = c.enabled ? 'primary stop' : 'primary';
    }
    $('preview').disabled = snapshot.busy;
    $('preview').textContent = snapshot.busy ? '采集中…' : '↻ 手动采集';
    if ($('overview-preview')) {
      $('overview-preview').disabled = snapshot.busy;
      $('overview-preview').textContent = snapshot.busy ? '采集中…' : '↻ 手动采集';
    }
    if ($('records-refresh-btn')) {
      $('records-refresh-btn').disabled = snapshot.busy;
      $('records-refresh-btn').textContent = snapshot.busy ? '采集中…' : '↻ 立即采集新数据';
    }
    $('capture').disabled = snapshot.capture_busy;
    $('capture').textContent = snapshot.capture_busy ? '等待群 @…' : '获取群标识';
    $('school-status').textContent = c.sdut_user && c.sdut_pwd_set ? '已配置' : '待配置';
    $('school-status').className = 'mini-status' + (c.sdut_user && c.sdut_pwd_set ? ' ready' : '');
    $('school-secret-note').textContent = c.sdut_pwd_set ? '密码已保存；留空保持原密码，填写可替换。' : '用于读取本人查寝记录及电量。';
    $('last-error').hidden = !snapshot.last_error;
    $('last-error').textContent = snapshot.last_error;
    $('connection').textContent = '● 服务已连接';
    $('records-copy').textContent = snapshot.fresh_count ? snapshot.fresh_count + ' 条未读记录 · 手动采集不推送；QQ 未启用时保留待推送。' : '手动采集不会发送 QQ 消息，也不会改变已读状态。';

    const fee = snapshot.fee;
    $('fee-state').textContent = fee.busy ? '正在 @全体发送' : !c.fee_enabled ? '提醒已关闭' : fee.status === 'sent' ? '本月已发送' : ['failed','sending'].includes(fee.status) ? '发送失败或结果待确认' : '每月提醒已开启';
    $('fee-next').textContent = !c.fee_enabled ? '开启后独立运行，不依赖查寝监测开关' : fee.next_at ? '下次：' + new Date(fee.next_at).toLocaleString('zh-CN', {timeZone:'Asia/Shanghai',hour12:false}) + ' · 北京时间' : '请先核对群内是否已收到，再决定是否重试';
    $('fee-error').hidden = !fee.error;
    $('fee-error').textContent = fee.error;
    $('fee-retry').hidden = !c.fee_enabled || fee.busy || !['failed','sending'].includes(fee.status);
    if (!dirty) updateFeePreview();

    const elc = snapshot.electricity || {}, result = elc.result;
    $('elc-query').disabled = !!elc.busy || snapshot.busy;
    $('elc-save').disabled = !!elc.busy;
    $('elc-query').textContent = elc.busy ? '查询中…' : '保存并立即查询';
    $('elc-balance').textContent = result?.remaining_kwh ?? '—';
    $('elc-detail').textContent = result ? (result.page_location || result.room) + ' · ' + new Date(result.checked_at).toLocaleString('zh-CN', {timeZone:'Asia/Shanghai', hour12:false}) + ' · ' + (result.balance_cny == null ? '人民币余额未提供' : '余额 ' + result.balance_cny + ' 元') : '尚无查询结果';
    $('elc-error').hidden = !elc.error;
    $('elc-error').textContent = elc.error || '';
    $('elc-next').textContent = !c.elc_enabled ? '电量自动采集已关闭' : elc.busy ? '采集执行中…' : '随统一计划同步轮询采集';

    if (!elcDirty) {
      $('elc-enabled').checked = Boolean(c.elc_enabled);
      if ($('elc-warn-thresholds') && c.elc_warn_thresholds) {
        $('elc-warn-thresholds').value = c.elc_warn_thresholds;
      }
    }

    // Overview electricity badge
    if ($('overview-elc-balance')) {
      $('overview-elc-balance').replaceChildren(document.createTextNode(result?.remaining_kwh ?? '—'), Object.assign(document.createElement('small'), {textContent:' 度'}));
      $('overview-elc-sub').textContent = result?.balance_cny != null ? `余额 ${result.balance_cny} 元` : (result ? '已查询' : '尚未查询');
      $('overview-elc-loc').textContent = result?.page_location || (c.elc_building ? `${c.elc_building} ${c.elc_room}` : '未配置');
      $('overview-elc-warns').textContent = c.elc_warn_thresholds ? `阈值线: ${c.elc_warn_thresholds} 度` : '未设阈值';
      $('overview-fee-status').textContent = c.fee_enabled ? (fee.status === 'sent' ? '本月已发送' : '已开启提醒') : '未开启';
    }

    renderRecords(snapshot.records);
    renderEvents();
    countdown();
  } catch (error) {
    $('connection').textContent = '○ 连接中断';
  } finally {
    refreshing = false;
  }
}

async function action(path, message) {
  try {
    await api(path, {});
    toast(message);
    await refresh();
  } catch (error) {
    toast(error.message, true);
  }
}

// Auth submission
$('auth-form').addEventListener('submit', async event => {
  event.preventDefault();
  $('auth-submit').disabled = true;
  $('auth-error').textContent = '';
  try {
    const result = await api(setupRequired ? '/api/setup' : '/api/login', {password:$('admin-password').value});
    csrf = result.csrf;
    $('admin-password').value = '';
    $('auth').hidden = true;
    $('app').hidden = false;
    hydrated = false;
    await refresh();
  } catch (error) {
    $('auth-error').textContent = error.message;
  } finally {
    $('auth-submit').disabled = false;
  }
});

// Config form
$('config-form').addEventListener('input', markDirty);
document.querySelectorAll('[data-minutes]').forEach(button => {
  button.addEventListener('click', () => {
    $('poll-minutes').value = button.dataset.minutes;
    markDirty();
  });
});

$('config-form').addEventListener('submit', async event => {
  event.preventDefault();
  $('save').disabled = true;
  try {
    await api('/api/config', {
      sdut_user: $('sdut-user').value,
      sdut_pwd: $('sdut-pwd').value,
      qq_appid: $('qq-appid').value,
      qq_secret: $('qq-secret').value,
      qq_group_openid: $('qq-group').value,
      push_enabled: $('push-enabled').checked,
      poll_minutes: Number($('poll-minutes').value),
      lookback_days: Number($('lookback-days').value),
      notification_provider: $('notification-provider').value,
      onebot_url: $('onebot-url').value,
      onebot_token: $('onebot-token').value,
      onebot_group_id: $('onebot-group').value,
      at_all_enabled: $('at-all-enabled').checked,
      template_dorm: $('template-dorm').value,
      template_fee: $('template-fee').value,
      template_elc: $('template-elc').value,
      fee_enabled: $('fee-enabled').checked,
      fee_day: Number($('fee-day').value),
      fee_time: $('fee-time').value,
      fee_people: Number($('fee-people').value),
      fee_amount: $('fee-amount').value,
      elc_warn_thresholds: $('elc-warn-thresholds') ? $('elc-warn-thresholds').value : '50, 20, 10, 5'
    });
    hydrated = false;
    await refresh();
    $('save-state').textContent = '✓ 配置已保存 · 无需重启服务';
    toast('配置已保存，计划与预警阈值已更新');
  } catch (error) {
    toast(error.message, true);
  } finally {
    $('save').disabled = false;
  }
});

// Action buttons
const triggerPreview = () => dirty ? toast('请先保存配置', true) : action('/api/preview', '已开始手动采集，不发送消息');
const triggerToggle = () => dirty && !snapshot.config.enabled ? toast('请先保存配置', true) : action(snapshot.config.enabled ? '/api/stop' : '/api/start', snapshot.config.enabled ? '监测已停止' : '监测已启动');

$('preview').addEventListener('click', triggerPreview);
$('toggle').addEventListener('click', triggerToggle);
if ($('overview-preview')) $('overview-preview').addEventListener('click', triggerPreview);
if ($('overview-toggle')) $('overview-toggle').addEventListener('click', triggerToggle);
if ($('records-refresh-btn')) $('records-refresh-btn').addEventListener('click', triggerPreview);

$('capture').addEventListener('click', () => dirty ? toast('请先保存机器人配置', true) : action('/api/capture-group', '正在连接，请在目标群 @ 机器人'));

// School test login
$('school-test-login').addEventListener('click', async () => {
  const user = $('sdut-user').value.trim();
  const pwd = $('sdut-pwd').value;
  if (!user) {
    toast('请先输入学号', true);
    return;
  }
  const btn = $('school-test-login');
  const fb = $('school-test-feedback');
  btn.disabled = true;
  btn.textContent = '测试登录中…';
  fb.className = 'school-test-feedback';
  fb.style.display = 'none';
  try {
    const res = await api('/api/test-login', {sdut_user: user, sdut_pwd: pwd});
    fb.className = 'school-test-feedback success';
    fb.textContent = '✓ ' + (res.message || '登录成功，统一身份认证连接正常！');
    fb.style.display = 'block';
    toast('学校账号登录测试通过！CAS SSO 连接正常');
    await refresh();
  } catch (err) {
    fb.className = 'school-test-feedback error';
    fb.textContent = '✕ ' + err.message;
    fb.style.display = 'block';
    toast(err.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = '测试账号登录 ↗';
  }
});

// Bot connection check
const checkBtn = $('channel-check');
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
    } catch (error) {
      toast(error.message, true);
    } finally {
      checkBtn.disabled = false;
    }
  });
}

// Bot test send
$('bot-test-send').addEventListener('click', async () => {
  if (dirty) { toast('请先保存群通知配置', true); return; }
  $('bot-test-send').disabled = true;
  try {
    await api('/api/bot-test-send', {});
    toast('测试消息已成功发送至目标群，请前往 QQ 查看');
    await refresh();
  } catch (error) {
    toast(error.message, true);
  } finally {
    $('bot-test-send').disabled = false;
  }
});

$('fee-retry').addEventListener('click', () => dirty ? toast('请先保存配置', true) : action('/api/fee-retry', '已按你的确认安排重试，请留意群消息'));
$('logout').addEventListener('click', async () => { await action('/api/logout', '已退出'); location.reload(); });

// Log filters
document.querySelectorAll('.log-filter-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.log-filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentLogFilter = btn.dataset.cat;
    renderEvents();
  });
});

$('logs-refresh-btn')?.addEventListener('click', async () => {
  await refresh();
  toast('日志已刷新');
});

// Tab navigation routing
document.querySelectorAll('.nav-item').forEach(link => {
  link.addEventListener('click', event => {
    event.preventDefault();
    const target = link.dataset.target || (link.getAttribute('href') || '').replace('#', '');
    switchView(target);
  });
});

document.querySelectorAll('.switch-view-btn').forEach(btn => {
  btn.addEventListener('click', () => switchView(btn.dataset.target));
});

window.addEventListener('hashchange', () => {
  const hash = (location.hash || '').replace('#', '');
  if (hash) switchView(hash);
});

// Fee day options
for (let day = 1; day <= 31; day++) {
  const option = document.createElement('option');
  option.value = day;
  option.textContent = '每月 ' + day + ' 日';
  $('fee-day').append(option);
}

// Electricity form
$('electricity-form').addEventListener('input', () => { elcDirty = true; });

async function saveElectricity(query) {
  if (dirty) { toast('请先保存上方学校账号和配置', true); return; }
  if (!$('electricity-form').reportValidity()) return;
  const values = {
    elc_campus: $('elc-campus').value,
    elc_building: $('elc-building').value,
    elc_floor: $('elc-floor').value,
    elc_room: $('elc-room').value,
    elc_type: $('elc-type').value,
    elc_enabled: $('elc-enabled').checked,
    elc_minutes: snapshot?.config?.poll_minutes || 15
  };
  const thresholds = $('elc-warn-thresholds').value;
  $('elc-query').disabled = true;
  $('elc-save').disabled = true;
  try {
    if (thresholds !== snapshot?.config?.elc_warn_thresholds) {
      await api('/api/config', {elc_warn_thresholds: thresholds});
    }
    await api(query ? '/api/electricity' : '/api/electricity-config', values);
    elcDirty = false;
    toast(query ? '已开始查询电量（复用学校会话）' : '电量配置与多级预警已保存');
    await refresh();
  } catch (error) {
    toast(error.message, true);
  } finally {
    $('elc-query').disabled = !!snapshot?.electricity?.busy;
    $('elc-save').disabled = !!snapshot?.electricity?.busy;
  }
}

$('electricity-form').addEventListener('submit', event => {
  event.preventDefault();
  saveElectricity(true);
});
$('elc-save').addEventListener('click', () => saveElectricity(false));

// Init
(async () => {
  try {
    const session = await api('/api/session');
    csrf = session.csrf || '';
    setupRequired = session.setup_required;
    if (session.authenticated) {
      $('auth').hidden = true;
      $('app').hidden = false;
      const initialView = (location.hash || '').replace('#', '') || 'overview';
      switchView(initialView);
      await refresh();
    } else {
      $('auth-title').textContent = setupRequired ? '创建你的管理空间' : '欢迎回来';
      $('auth-copy').textContent = setupRequired ? '首次使用，请设置一个管理密码。之后学校和机器人配置都在网页完成。' : '输入管理密码，继续查看查寝更新。';
      $('auth-submit').textContent = setupRequired ? '设置密码并进入 ↗' : '登录控制台 ↗';
    }
  } catch (error) {
    $('auth-error').textContent = '无法连接服务，请刷新重试。';
  }
})();

setInterval(refresh, 4000);
setInterval(countdown, 1000);
