/**
 * Telegram Integration Page
 * 
 * Features:
 * - Bot token configuration
 * - DM policy settings
 * - Pending approvals (pairing mode)
 * - Connected users list
 * - Test message capability
 */

import { useState, useEffect } from "react";
import {
  getTelegramConfig,
  updateTelegramConfig,
  listPendingTelegramUsers,
  listTelegramUsers,
  approveTelegramUser,
  sendTelegramTestMessage,
  type TelegramConfig,
  type TelegramUser,
} from "../lib/api";

export default function TelegramPage() {
  const [config, setConfig] = useState<TelegramConfig | null>(null);
  const [botToken, setBotToken] = useState("");
  const [dmPolicy, setDmPolicy] = useState<'pairing' | 'allowlist' | 'open'>('pairing');
  const [pendingUsers, setPendingUsers] = useState<TelegramUser[]>([]);
  const [connectedUsers, setConnectedUsers] = useState<TelegramUser[]>([]);
  const [saving, setSaving] = useState(false);
  const [testMessageStatus, setTestMessageStatus] = useState<string | null>(null);

  useEffect(() => {
    loadConfig();
    loadPendingUsers();
    loadConnectedUsers();
  }, []);

  const loadConfig = async () => {
    try {
      const data = await getTelegramConfig();
      setConfig(data);
      setDmPolicy(data.dm_policy || 'pairing');
    } catch (err) {
      console.error('Failed to load Telegram config:', err);
    }
  };

  const loadPendingUsers = async () => {
    try {
      const data = await listPendingTelegramUsers();
      setPendingUsers(data.pending_users || []);
    } catch (err) {
      console.error('Failed to load pending users:', err);
    }
  };

  const loadConnectedUsers = async () => {
    try {
      const data = await listTelegramUsers();
      setConnectedUsers(data.users?.filter((u) => u.approved) || []);
    } catch (err) {
      console.error('Failed to load connected users:', err);
    }
  };

  const handleSaveConfig = async () => {
    setSaving(true);
    try {
      const result = await updateTelegramConfig({
        bot_token: botToken,
        dm_policy: dmPolicy,
      });
      alert(result.message || 'Configuration saved!');
      loadConfig();
    } catch (err) {
      alert(`Error: ${err instanceof Error ? err.message : 'Unknown error'}`);
    } finally {
      setSaving(false);
    }
  };

  const handleApproveUser = async (telegramId: string) => {
    try {
      await approveTelegramUser(telegramId);
      loadPendingUsers();
      loadConnectedUsers();
      alert('User approved successfully!');
    } catch (err) {
      alert(`Error: ${err instanceof Error ? err.message : 'Unknown error'}`);
    }
  };

  const handleTestMessage = async () => {
    setTestMessageStatus('Sending...');
    try {
      const result = await sendTelegramTestMessage();
      setTestMessageStatus(result.message);
    } catch (err) {
      setTestMessageStatus(`Error: ${err instanceof Error ? err.message : 'Failed to send test message'}`);
    }
  };

  return (
    <div style={{ padding: '20px', height: '100%', overflow: 'auto' }}>
      <h1 style={{ marginBottom: '24px' }}>Telegram Integration</h1>

      {/* Bot Configuration */}
      <section className="card" style={{ 
        background: 'var(--bg-secondary)', 
        padding: '20px',
        marginBottom: '24px',
      }}>
        <h2 style={{ marginTop: 0, marginBottom: '16px' }}>🤖 Bot Configuration</h2>
        
        <div style={{ marginBottom: '16px' }}>
          <label style={{ display: 'block', marginBottom: '8px', fontSize: '13px' }}>
            Bot Token (from @BotFather)
          </label>
          <input
            type="password"
            className="input"
            value={botToken}
            onChange={(e) => setBotToken(e.target.value)}
            placeholder="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
            style={{ width: '100%', fontFamily: 'monospace' }}
          />
          <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
            Current: {config?.bot_token_set ? '✅ Configured' : '❌ Not configured'}
          </div>
        </div>

        <div style={{ marginBottom: '16px' }}>
          <label style={{ display: 'block', marginBottom: '8px', fontSize: '13px' }}>
            DM Policy
          </label>
          <select
            className="input"
            value={dmPolicy}
            onChange={(e) => setDmPolicy(e.target.value as any)}
            style={{ width: '100%' }}
          >
            <option value="pairing">Pairing (require approval code)</option>
            <option value="allowlist">Allowlist only</option>
            <option value="open">Open (anyone can message)</option>
          </select>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
            {dmPolicy === 'pairing' && 'Users need approval code from administrator'}
            {dmPolicy === 'allowlist' && 'Only pre-approved users can message'}
            {dmPolicy === 'open' && 'Anyone can message the bot'}
          </div>
        </div>

        <button
          className="btn btn-primary"
          onClick={handleSaveConfig}
          disabled={saving}
        >
          {saving ? 'Saving...' : '💾 Save Configuration'}
        </button>
        <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '8px' }}>
          ⚠️ Bot token changes require restart to take effect
        </div>
      </section>

      {/* Test Message */}
      <section className="card" style={{ 
        background: 'var(--bg-secondary)', 
        padding: '20px',
        marginBottom: '24px',
      }}>
        <h2 style={{ marginTop: 0, marginBottom: '16px' }}>🧪 Test Connection</h2>
        
        <button
          className="btn btn-secondary"
          onClick={handleTestMessage}
          disabled={!config?.bot_token_set}
        >
          Send Test Message
        </button>
        
        {testMessageStatus && (
          <div style={{
            marginTop: '12px',
            padding: '12px',
            borderRadius: '8px',
            background: testMessageStatus.includes('Error') ? 'var(--error-bg)' : 'var(--success-bg)',
            border: `1px solid ${testMessageStatus.includes('Error') ? 'var(--error-color)' : 'var(--success-color)'}`,
            fontSize: '13px',
            color: testMessageStatus.includes('Error') ? 'var(--error-color)' : 'var(--success-color)',
          }}>
            {testMessageStatus}
          </div>
        )}
      </section>

      {/* Pending Approvals */}
      {dmPolicy === 'pairing' && (
        <section className="card" style={{ 
          background: 'var(--bg-secondary)', 
          padding: '20px',
          marginBottom: '24px',
        }}>
          <h2 style={{ marginTop: 0, marginBottom: '16px' }}>⏳ Pending Approvals</h2>
          
          {pendingUsers.length === 0 ? (
            <div className="empty-state">
              <div className="empty-state-icon">✅</div>
              <div className="empty-state-title">No Pending Approvals</div>
              <div className="empty-state-text">
                All users have been approved
              </div>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {pendingUsers.map((user) => (
                <div
                  key={user.telegram_id}
                  style={{
                    background: 'var(--bg-input)',
                    padding: '12px',
                    borderRadius: '8px',
                    border: '1px solid var(--border)',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                  }}
                >
                  <div>
                    <div style={{ fontSize: '13px', fontWeight: 600 }}>
                      Telegram ID: {user.telegram_id}
                    </div>
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                      User ID: {user.user_id} • Created: {new Date(user.created_at).toLocaleString()}
                    </div>
                  </div>
                  <button
                    className="btn btn-success"
                    onClick={() => handleApproveUser(user.telegram_id)}
                  >
                    ✅ Approve
                  </button>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {/* Connected Users */}
      <section className="card" style={{ 
        background: 'var(--bg-secondary)', 
        padding: '20px',
        marginBottom: '24px',
      }}>
        <h2 style={{ marginTop: 0, marginBottom: '16px' }}>👥 Connected Users</h2>
        
        {connectedUsers.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">👥</div>
            <div className="empty-state-title">No Connected Users</div>
            <div className="empty-state-text">
              Users will appear here once they connect to the bot
            </div>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {connectedUsers.map((user) => (
              <div
                key={user.telegram_id}
                style={{
                  background: 'var(--bg-input)',
                  padding: '12px',
                  borderRadius: '8px',
                  border: '1px solid var(--border)',
                }}
              >
                <div style={{ fontSize: '13px', fontWeight: 600, marginBottom: '4px' }}>
                  Telegram ID: {user.telegram_id}
                </div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                  User ID: {user.user_id} • Created: {new Date(user.created_at).toLocaleString()}
                  {user.last_message_at && (
                    <> • Last Active: {new Date(user.last_message_at).toLocaleString()}</>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Setup Instructions */}
      <section className="card" style={{ 
        background: 'var(--bg-secondary)', 
        padding: '20px',
      }}>
        <h2 style={{ marginTop: 0, marginBottom: '16px' }}>📚 Setup Instructions</h2>
        
        <div style={{ fontSize: '13px', lineHeight: 1.8 }}>
          <h3 style={{ fontSize: '14px', marginBottom: '8px' }}>1. Create a Bot</h3>
          <ol style={{ paddingLeft: '20px', marginBottom: '16px' }}>
            <li>Open Telegram and search for <strong>@BotFather</strong></li>
            <li>Send <code>/newbot</code> and follow the instructions</li>
            <li>Choose a name and username for your bot</li>
            <li>Copy the bot token provided by BotFather</li>
          </ol>

          <h3 style={{ fontSize: '14px', marginBottom: '8px' }}>2. Configure the Bot</h3>
          <ol style={{ paddingLeft: '20px', marginBottom: '16px' }}>
            <li>Paste the bot token in the "Bot Token" field above</li>
            <li>Choose your preferred DM Policy</li>
            <li>Click "Save Configuration"</li>
            <li>Restart the application for bot token changes to take effect</li>
          </ol>

          <h3 style={{ fontSize: '14px', marginBottom: '8px' }}>3. Start the Bot</h3>
          <ol style={{ paddingLeft: '20px', marginBottom: '16px' }}>
            <li>Run: <code>python -m packages.messaging.telegram_bot</code></li>
            <li>Or use webhook mode for production deployment</li>
          </ol>

          <h3 style={{ fontSize: '14px', marginBottom: '8px' }}>4. Test the Connection</h3>
          <ol style={{ paddingLeft: '20px' }}>
            <li>Click "Send Test Message" to verify the bot is working</li>
            <li>Users can now message your bot on Telegram</li>
            {dmPolicy === 'pairing' && (
              <>
                <li>Approve pending users from the "Pending Approvals" section</li>
                <li>Share the approval code with users</li>
              </>
            )}
          </ol>
        </div>
      </section>
    </div>
  );
}
