/**
 * Workspace Page - Expanded with Permission Tester
 */

import { useState, useEffect } from "react";
import {
  listWorkspaces,
  createWorkspace,
  deleteWorkspace,
  getAuditLog,
  checkPermission,
  type Workspace,
  type AuditLogEntry,
} from "../lib/workspace-api";

interface PermissionTest {
  path: string;
  action: 'read' | 'write' | 'execute';
  result?: {
    allowed: boolean;
    reason: string;
  };
}

export default function WorkspacePage() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [selectedWorkspace, setSelectedWorkspace] = useState<Workspace | null>(null);
  const [auditLog, setAuditLog] = useState<AuditLogEntry[]>([]);
  const [showAuditLog, setShowAuditLog] = useState(false);
  
  // Permission tester state
  const [showPermissionTester, setShowPermissionTester] = useState(false);
  const [permissionTest, setPermissionTest] = useState<PermissionTest>({
    path: "",
    action: "read",
  });
  const [testingPermission, setTestingPermission] = useState(false);

  // Form state
  const [formData, setFormData] = useState({
    project_id: "",
    root: "",
    read_patterns: "**/*",
    write_patterns: "src/**/*",
    execute: false,
    git_operations: true,
    network_access: false,
    agent_instructions: "",
  });

  useEffect(() => {
    loadWorkspaces();
  }, []);

  const loadWorkspaces = async () => {
    try {
      setLoading(true);
      const list = await listWorkspaces();
      setWorkspaces(list);
    } catch (err) {
      console.error("Failed to load workspaces:", err);
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();

    try {
      await createWorkspace({
        project_id: formData.project_id,
        root: formData.root,
        permissions: {
          read: formData.read_patterns.split(",").map(p => p.trim()),
          write: formData.write_patterns.split(",").map(p => p.trim()),
          execute: formData.execute,
          git_operations: formData.git_operations,
          network_access: formData.network_access,
        },
        agent_instructions: formData.agent_instructions,
        context_collection: `project_${formData.project_id}`,
      });

      setShowCreateForm(false);
      setFormData({
        project_id: "",
        root: "",
        read_patterns: "**/*",
        write_patterns: "src/**/*",
        execute: false,
        git_operations: true,
        network_access: false,
        agent_instructions: "",
      });
      loadWorkspaces();
    } catch (err) {
      alert(`Failed to create workspace: ${err}`);
    }
  };

  const handleDelete = async (projectId: string) => {
    if (!confirm(`Delete workspace "${projectId}"?`)) return;

    try {
      await deleteWorkspace(projectId);
      loadWorkspaces();
      if (selectedWorkspace?.project_id === projectId) {
        setSelectedWorkspace(null);
      }
    } catch (err) {
      alert(`Failed to delete workspace: ${err}`);
    }
  };

  const loadAuditLog = async (projectId: string) => {
    try {
      const log = await getAuditLog(projectId, 50);
      setAuditLog(log);
      setShowAuditLog(true);
    } catch (err) {
      alert(`Failed to load audit log: ${err}`);
    }
  };

  const handleTestPermission = async () => {
    if (!selectedWorkspace || !permissionTest.path.trim()) return;

    setTestingPermission(true);
    try {
      const result = await checkPermission(selectedWorkspace.project_id, {
        path: permissionTest.path,
        action: permissionTest.action,
      });
      setPermissionTest(prev => ({ ...prev, result }));
    } catch (err) {
      alert(`Error: ${err instanceof Error ? err.message : 'Unknown error'}`);
    } finally {
      setTestingPermission(false);
    }
  };

  return (
    <div style={{ padding: '20px', height: '100%', overflow: 'auto' }}>
      <div style={{ 
        display: 'flex', 
        justifyContent: 'space-between', 
        alignItems: 'center',
        marginBottom: '20px',
      }}>
        <h1 style={{ margin: 0 }}>Workspace Management</h1>
        <div style={{ display: 'flex', gap: '12px' }}>
          <button
            className="btn btn-secondary"
            onClick={() => setShowPermissionTester(true)}
            disabled={!selectedWorkspace}
            title={selectedWorkspace ? "Test permissions" : "Select a workspace first"}
          >
            🔒 Test Permissions
          </button>
          <button
            className="btn btn-primary"
            onClick={() => setShowCreateForm(!showCreateForm)}
          >
            {showCreateForm ? "Cancel" : "+ New Workspace"}
          </button>
        </div>
      </div>

      {/* Create Form */}
      {showCreateForm && (
        <form onSubmit={handleCreate} style={{
          background: "var(--bg-secondary)",
          padding: "20px",
          borderRadius: "8px",
          marginBottom: "20px",
        }}>
          <div style={{ display: "grid", gap: "16px", gridTemplateColumns: "1fr 1fr" }}>
            <div>
              <label style={{ display: "block", marginBottom: "8px" }}>Project ID</label>
              <input
                type="text"
                className="input"
                value={formData.project_id}
                onChange={(e) => setFormData({ ...formData, project_id: e.target.value })}
                required
                placeholder="my-project"
              />
            </div>
            
            <div>
              <label style={{ display: "block", marginBottom: "8px" }}>Root Path</label>
              <input
                type="text"
                className="input"
                value={formData.root}
                onChange={(e) => setFormData({ ...formData, root: e.target.value })}
                required
                placeholder="C:\Agents\PersonalAssist"
              />
            </div>

            <div>
              <label style={{ display: "block", marginBottom: "8px" }}>Read Patterns</label>
              <input
                type="text"
                className="input"
                value={formData.read_patterns}
                onChange={(e) => setFormData({ ...formData, read_patterns: e.target.value })}
                placeholder="**/*, src/**/*"
              />
            </div>

            <div>
              <label style={{ display: "block", marginBottom: "8px" }}>Write Patterns</label>
              <input
                type="text"
                className="input"
                value={formData.write_patterns}
                onChange={(e) => setFormData({ ...formData, write_patterns: e.target.value })}
                placeholder="src/**/*, tests/**/*"
              />
            </div>

            <div>
              <label style={{ display: "block", marginBottom: "8px" }}>Agent Instructions</label>
              <textarea
                className="input"
                value={formData.agent_instructions}
                onChange={(e) => setFormData({ ...formData, agent_instructions: e.target.value })}
                rows={3}
                placeholder="Focus on code quality..."
              />
            </div>

            <div style={{ display: "flex", gap: "16px", alignItems: "center" }}>
              <label style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <input
                  type="checkbox"
                  checked={formData.execute}
                  onChange={(e) => setFormData({ ...formData, execute: e.target.checked })}
                />
                Allow Execute
              </label>
              
              <label style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <input
                  type="checkbox"
                  checked={formData.git_operations}
                  onChange={(e) => setFormData({ ...formData, git_operations: e.target.checked })}
                />
                Git Operations
              </label>
              
              <label style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <input
                  type="checkbox"
                  checked={formData.network_access}
                  onChange={(e) => setFormData({ ...formData, network_access: e.target.checked })}
                />
                Network Access
              </label>
            </div>
          </div>

          <button type="submit" className="btn btn-primary" style={{ marginTop: "16px" }}>
            Create Workspace
          </button>
        </form>
      )}

      {/* Workspace List */}
      {loading ? (
        <div className="empty-state">
          <div className="spinner" />
          <div>Loading workspaces...</div>
        </div>
      ) : workspaces.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">📁</div>
          <div className="empty-state-title">No Workspaces</div>
          <div className="empty-state-text">
            Create a workspace to configure agent permissions and access controls
          </div>
        </div>
      ) : (
        <div style={{ display: "grid", gap: "16px" }}>
          {workspaces.map((workspace) => (
            <div
              key={workspace.project_id}
              className="card"
              style={{
                background: "var(--bg-card)",
                padding: "16px",
                borderRadius: "8px",
                cursor: "pointer",
                border: selectedWorkspace?.project_id === workspace.project_id
                  ? "2px solid var(--accent-primary)"
                  : "2px solid transparent",
              }}
              onClick={() => setSelectedWorkspace(workspace)}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <h3 style={{ margin: "0 0 8px 0" }}>{workspace.project_id}</h3>
                  <div style={{ fontSize: "13px", color: "var(--text-muted)", marginBottom: "8px" }}>
                    📁 {workspace.root}
                  </div>
                  <div style={{ fontSize: "12px", color: "var(--text-muted)" }}>
                    Read: {workspace.permissions.read.join(", ")} | 
                    Write: {workspace.permissions.write.join(", ") || "None"}
                  </div>
                </div>
                
                <div style={{ display: "flex", gap: "8px" }}>
                  <button
                    className="btn btn-secondary"
                    onClick={(e) => {
                      e.stopPropagation();
                      loadAuditLog(workspace.project_id);
                    }}
                    title="View Audit Log"
                  >
                    📋
                  </button>
                  <button
                    className="btn btn-danger"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDelete(workspace.project_id);
                    }}
                    title="Delete Workspace"
                  >
                    🗑️
                  </button>
                </div>
              </div>
              
              <div style={{ marginTop: "12px", display: "flex", gap: "8px" }}>
                {workspace.permissions.execute && (
                  <span className="badge badge-accent">⚡ Execute</span>
                )}
                {workspace.permissions.git_operations && (
                  <span className="badge badge-success">🔀 Git</span>
                )}
                {workspace.permissions.network_access && (
                  <span className="badge badge-warning">🌐 Network</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Audit Log Modal */}
      {showAuditLog && (
        <div style={{
          position: "fixed",
          top: 0, left: 0, right: 0, bottom: 0,
          background: "var(--bg-overlay)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          zIndex: 1000,
        }} onClick={() => setShowAuditLog(false)}>
          <div
            style={{
              background: "var(--bg-modal)",
              border: "1px solid var(--border)",
              padding: "20px",
              borderRadius: "12px",
              maxWidth: "800px",
              maxHeight: "80vh",
              overflow: "auto",
              boxShadow: "var(--shadow-lg)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <h2 style={{ marginTop: 0 }}>Audit Log — {selectedWorkspace?.project_id}</h2>

            {auditLog.length === 0 ? (
              <div className="empty-state">
                <div>No audit entries yet</div>
              </div>
            ) : (
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
                <thead>
                  <tr style={{ borderBottom: "2px solid var(--border)" }}>
                    <th style={{ padding: "8px", textAlign: "left" }}>Time</th>
                    <th style={{ padding: "8px", textAlign: "left" }}>Action</th>
                    <th style={{ padding: "8px", textAlign: "left" }}>Target</th>
                    <th style={{ padding: "8px", textAlign: "left" }}>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {auditLog.map((entry, i) => (
                    <tr
                      key={i}
                      style={{
                        borderBottom: "1px solid var(--border)",
                        background: entry.allowed ? "var(--audit-allowed-bg)" : "var(--audit-denied-bg)",
                      }}
                    >
                      <td style={{ padding: "8px", fontFamily: "monospace", fontSize: "11px" }}>
                        {new Date(entry.timestamp).toLocaleString()}
                      </td>
                      <td style={{ padding: "8px" }}>{entry.action}</td>
                      <td style={{ padding: "8px", fontFamily: "monospace", fontSize: "12px" }}>
                        {entry.target}
                      </td>
                      <td style={{ padding: "8px" }}>
                        <span className={`badge ${entry.allowed ? "badge-success" : "badge-danger"}`}>
                          {entry.allowed ? "✓ Allowed" : "✗ Denied"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            <button
              className="btn btn-secondary"
              onClick={() => setShowAuditLog(false)}
              style={{ marginTop: "16px" }}
            >
              Close
            </button>
          </div>
        </div>
      )}

      {/* Permission Tester Modal */}
      {showPermissionTester && selectedWorkspace && (
        <div
          style={{
            position: "fixed",
            top: 0, left: 0, right: 0, bottom: 0,
            background: "var(--bg-overlay)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
          }}
          onClick={() => {
            setShowPermissionTester(false);
            setPermissionTest({ path: "", action: "read" });
          }}
        >
          <div
            style={{
              background: "var(--bg-modal)",
              border: "1px solid var(--border)",
              padding: "24px",
              borderRadius: "12px",
              maxWidth: "500px",
              width: "90%",
              boxShadow: "var(--shadow-lg)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 style={{ marginTop: 0 }}>🔒 Permission Tester</h3>
            <p style={{ fontSize: "13px", color: "var(--text-muted)", marginTop: "-16px" }}>
              Test if a path has specific permissions in workspace: <strong>{selectedWorkspace.project_id}</strong>
            </p>

            <div style={{ marginBottom: "16px" }}>
              <label style={{ display: "block", marginBottom: "8px", fontSize: "13px" }}>
                Path to Test
              </label>
              <input
                type="text"
                className="input"
                value={permissionTest.path}
                onChange={(e) => setPermissionTest(prev => ({ ...prev, path: e.target.value }))}
                placeholder="src/main.py"
                style={{ width: "100%" }}
              />
            </div>

            <div style={{ marginBottom: "16px" }}>
              <label style={{ display: "block", marginBottom: "8px", fontSize: "13px" }}>
                Action
              </label>
              <select
                className="input"
                value={permissionTest.action}
                onChange={(e) => setPermissionTest(prev => ({ ...prev, action: e.target.value as any }))}
                style={{ width: "100%" }}
              >
                <option value="read">Read</option>
                <option value="write">Write</option>
                <option value="execute">Execute</option>
              </select>
            </div>

            {permissionTest.result && (
              <div style={{
                marginBottom: "16px",
                padding: "12px",
                borderRadius: "8px",
                background: permissionTest.result.allowed
                  ? "var(--permission-allowed-bg)"
                  : "var(--permission-denied-bg)",
                border: `1px solid ${permissionTest.result.allowed ? "var(--success-color)" : "var(--error-color)"}`,
              }}>
                <div style={{ fontSize: "12px", fontWeight: 600, marginBottom: "4px" }}>
                  {permissionTest.result.allowed ? "✅ Allowed" : "❌ Denied"}
                </div>
                <div style={{ fontSize: "11px" }}>
                  {permissionTest.result.reason}
                </div>
              </div>
            )}

            <div style={{ display: "flex", gap: "12px", justifyContent: "flex-end" }}>
              <button
                className="btn btn-secondary"
                onClick={() => {
                  setShowPermissionTester(false);
                  setPermissionTest({ path: "", action: "read" });
                }}
              >
                Close
              </button>
              <button
                className="btn btn-primary"
                onClick={handleTestPermission}
                disabled={testingPermission || !permissionTest.path.trim()}
              >
                {testingPermission ? "Testing..." : "🔍 Test Permission"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Selected Workspace Details */}
      {selectedWorkspace && !showAuditLog && !showPermissionTester && (
        <div style={{
          position: "fixed",
          bottom: "20px",
          right: "20px",
          width: "400px",
          background: "var(--bg-modal)",
          border: "1px solid var(--border)",
          padding: "16px",
          borderRadius: "12px",
          boxShadow: "var(--shadow-lg)",
        }}>
          <h3 style={{ marginTop: 0 }}>{selectedWorkspace.project_id}</h3>
          <div style={{ fontSize: "13px", color: "var(--text-muted)" }}>
            <div><strong>Root:</strong> {selectedWorkspace.root}</div>
            <div><strong>Read:</strong> {selectedWorkspace.permissions.read.join(", ")}</div>
            <div><strong>Write:</strong> {selectedWorkspace.permissions.write.join(", ") || "None"}</div>
            <div><strong>Execute:</strong> {selectedWorkspace.permissions.execute ? "Yes" : "No"}</div>
            <div><strong>Git:</strong> {selectedWorkspace.permissions.git_operations ? "Yes" : "No"}</div>
            <div><strong>Network:</strong> {selectedWorkspace.permissions.network_access ? "Yes" : "No"}</div>
          </div>
          <button
            className="btn btn-secondary"
            onClick={() => setSelectedWorkspace(null)}
            style={{ marginTop: "12px" }}
          >
            Close
          </button>
        </div>
      )}
    </div>
  );
}
