import React, { useState, useEffect } from 'react';

const API_BASE = "http://localhost:8000/api";

export default function App() {
  // Session & Navigation State
  const [user, setUser] = useState(JSON.parse(localStorage.getItem('user')) || null);
  const [currentPage, setCurrentPage] = useState(user ? "Dashboard" : "Auth");
  const [activeTab, setActiveTab] = useState("analysis");
  const [showProfileDropdown, setShowProfileDropdown] = useState(false);

  // Authentication Forms State
  const [isLoginTab, setIsLoginTab] = useState(true);
  const [loginForm, setLoginForm] = useState({ username: "", password: "" });
  const [registerForm, setRegisterForm] = useState({ username: "", password: "", fullName: "", email: "", confirmPassword: "" });
  const [authError, setAuthError] = useState("");
  const [authSuccess, setAuthSuccess] = useState("");

  // Analysis Workspace State
  const [selectedFile, setSelectedFile] = useState(null);
  const [isExtracting, setIsExtracting] = useState(false);
  const [extractedText, setExtractedText] = useState("");
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analysisResults, setAnalysisResults] = useState([]);

  // User History State
  const [historyList, setHistoryList] = useState([]);

  // Admin Verification State
  const [pendingLogs, setPendingLogs] = useState([]);
  const [expandedLogId, setExpandedLogId] = useState(null);
  const [editedOutputs, setEditedOutputs] = useState({});

  // User Profile Edit State
  const [profileForm, setProfileForm] = useState({ fullName: "", email: "" });
  const [profileMsg, setProfileMsg] = useState({ type: "", text: "" });

  const [analysisProgress, setAnalysisProgress] = useState({ current: 0, total: 0 });

  // Fetch histories and pending logs dynamically based on states
  useEffect(() => {
    if (user) {
      fetchHistory();
      if (user.role === "Admin") {
        fetchPendingLogs();
      }
    }
  }, [user]);

  // Handle outside click for dropdown
  useEffect(() => {
    const closeDropdown = () => setShowProfileDropdown(false);
    document.addEventListener("click", closeDropdown);
    return () => document.removeEventListener("click", closeDropdown);
  }, []);

  // API Call Helpers
  const fetchHistory = async () => {
    try {
      const res = await fetch(`${API_BASE}/history/${user.username}`);
      if (res.ok) {
        const data = await res.json();
        setHistoryList(data);
      }
    } catch (e) { console.error("Error fetching history", e); }
  };

  const fetchPendingLogs = async () => {
    try {
      const res = await fetch(`${API_BASE}/admin/logs`);
      if (res.ok) {
        const data = await res.json();
        setPendingLogs(data);
      }
    } catch (e) { console.error("Error fetching logs", e); }
  };

  // Auth Operations
  const handleLogin = async (e) => {
    e.preventDefault();
    setAuthError("");
    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: loginForm.username, password: loginForm.password })
      });
      const data = await res.json();
      if (res.ok) {
        localStorage.setItem('user', JSON.stringify(data));
        setUser(data);
        setProfileForm({ fullName: data.full_name, email: data.email });
        setCurrentPage("Dashboard");
      } else {
        setAuthError(data.detail || "Login failed.");
      }
    } catch (err) {
      setAuthError("Could not connect to authentication server.");
    }
  };

  const handleRegister = async (e) => {
    e.preventDefault();
    setAuthError("");
    setAuthSuccess("");
    if (registerForm.password !== registerForm.confirmPassword) {
      setAuthError("Passwords do not match.");
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: registerForm.username,
          password: registerForm.password,
          full_name: registerForm.fullName,
          email: registerForm.email
        })
      });
      const data = await res.json();
      if (res.ok) {
        setAuthSuccess("Registration successful! You can now log in.");
        setIsLoginTab(true);
      } else {
        setAuthError(data.detail || "Registration failed.");
      }
    } catch (err) {
      setAuthError("Could not connect to authentication server.");
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('user');
    setUser(null);
    setCurrentPage("Auth");
    setAnalysisResults([]);
    setExtractedText("");
  };

  // File parsing and Model Run workflows
  const handleExtractText = async () => {
    if (!selectedFile) return;
    setIsExtracting(true);
    const formData = new FormData();
    formData.append("file", selectedFile);
    try {
      const res = await fetch(`${API_BASE}/analysis/upload`, {
        method: "POST",
        body: formData
      });
      const data = await res.json();
      if (res.ok) {
        setExtractedText(data.extracted_text);
        setAnalysisResults([]);
      } else {
        alert(data.detail || "Failed to extract text.");
      }
    } catch (err) {
      alert("Error uploading file.");
    } finally {
      setIsExtracting(false);
    }
  };

const handleRunAnalysis = async () => {
    if (!extractedText.trim()) return;
    setIsAnalyzing(true);
    setAnalysisResults([]); // Reset previous results so new cards populate sequentially
    setAnalysisProgress({ current: 0, total: 0 });

    try {
      const response = await fetch(`${API_BASE}/analysis/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: user.username, raw_text: extractedText })
      });

      if (!response.ok) {
        alert("Error running analysis pipeline.");
        setIsAnalyzing(false);
        return;
      }

      // Initialize reader to decode stream packets
      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        // Decode incoming binary chunks into text lines
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");

        // Keep the last incomplete fragment in the buffer
        buffer = lines.pop();

        for (const line of lines) {
          if (line.trim() === "") continue;
          try {
            const chunk = JSON.parse(line);
            
            if (chunk.type === "empty") {
              alert(chunk.message);
            } else if (chunk.type === "result") {
              // Append the newly arrived card dynamically to the UI array
              setAnalysisResults((prev) => [...prev, chunk.data]);
              setAnalysisProgress(chunk.progress);
            }
          } catch (e) {
            console.error("Failed to parse dynamic chunk:", line, e);
          }
        }
      }
      
      // Update history tab
      fetchHistory();

    } catch (e) {
      alert("Failed to connect to backend engine.");
    } finally {
      setIsAnalyzing(false);
    }
  };

  // Admin Curation Operations
  const handleApproveLog = async (logId) => {
    const valText = editedOutputs[logId] !== undefined ? editedOutputs[logId] : pendingLogs.find(l => l.id === logId)?.model_output;
    try {
      const res = await fetch(`${API_BASE}/admin/logs/${logId}/validate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ validated_text: valText, status: "Validated" })
      });
      if (res.ok) {
        setPendingLogs(prev => prev.filter(l => l.id !== logId));
        alert(`Log ID #${logId} validated and exported.`);
      }
    } catch (e) { console.error(e); }
  };

  const handleDeleteLog = async (logId) => {
    if (!confirm("Are you sure you want to discard this log?")) return;
    try {
      const res = await fetch(`${API_BASE}/admin/logs/${logId}`, { method: "DELETE" });
      if (res.ok) {
        setPendingLogs(prev => prev.filter(l => l.id !== logId));
      }
    } catch (e) { console.error(e); }
  };

  // Profile Update Operations
  const handleSaveProfile = async (e) => {
    e.preventDefault();
    setProfileMsg({ type: "", text: "" });
    try {
      const res = await fetch(`${API_BASE}/profile`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: user.username,
          full_name: profileForm.fullName,
          email: profileForm.email
        })
      });
      if (res.ok) {
        const updatedUser = { ...user, full_name: profileForm.fullName, email: profileForm.email };
        localStorage.setItem('user', JSON.stringify(updatedUser));
        setUser(updatedUser);
        setProfileMsg({ type: "success", text: "Profile updated successfully!" });
      } else {
        setProfileMsg({ type: "error", text: "Failed to save profile." });
      }
    } catch (e) {
      setProfileMsg({ type: "error", text: "Network error saving profile." });
    }
  };

  // UI Scannability Formatter
  const formatScannableClause = (raw, limit = 200) => {
    let clean = raw.trim().replace(/^[a-z\s,.\-\)]+/, '');
    if (clean && clean[0] === clean[0].toLowerCase()) {
      clean = clean[0].toUpperCase() + clean.slice(1);
    }
    return clean.length > limit ? clean.slice(0, limit) + "..." : clean;
  };

  return (
    <div className="min-h-screen bg-gray-50 text-gray-800 flex flex-col font-sans">
      
      {/* HEADER SECTION */}
      <header className="bg-white border-b border-gray-200 px-6 py-4 flex justify-between items-center sticky top-0 z-50 shadow-sm">
        <div className="flex items-center space-x-2">
          <span className="text-2xl" role="img" aria-label="shield">🛡️</span>
          <h1 className="text-xl font-bold tracking-tight text-gray-900">SpecGuard</h1>
        </div>

        {user && (
          <div className="relative">
            <button 
              onClick={(e) => { e.stopPropagation(); setShowProfileDropdown(!showProfileDropdown); }}
              className="bg-gray-100 hover:bg-gray-200 text-gray-700 px-4 py-2 rounded-lg flex items-center space-x-2 border border-gray-200 transition focus:outline-none"
            >
              <span>👤</span>
              <span className="font-semibold">{user.full_name}</span>
              <span className="text-xs">▼</span>
            </button>
            {showProfileDropdown && (
              <div className="absolute right-0 mt-2 w-56 bg-white border border-gray-200 rounded-lg shadow-lg py-2 z-50">
                <div className="px-4 py-2 text-xs text-gray-500 border-b border-gray-100">
                  <p className="font-bold text-gray-700">Role: {user.role}</p>
                  <p className="truncate">{user.email}</p>
                </div>
                <button 
                  onClick={() => { setCurrentPage("Profile"); setShowProfileDropdown(false); }}
                  className="w-full text-left px-4 py-2 text-sm hover:bg-gray-100 transition"
                >
                  Personal Profile
                </button>
                <button 
                  onClick={handleLogout}
                  className="w-full text-left px-4 py-2 text-sm text-red-600 hover:bg-red-50 transition border-t border-gray-100"
                >
                  Logout
                </button>
              </div>
            )}
          </div>
        )}
      </header>

      {/* CENTRAL LAYOUT CONTROLLER */}
      <main className="flex-grow p-6 max-w-7xl w-full mx-auto">
        
        {/* VIEW 1: AUTH PAGE */}
        {currentPage === "Auth" && (
          <div className="max-w-md mx-auto my-12 bg-white rounded-xl border border-gray-200 shadow-sm p-8">
            <h2 className="text-2xl font-bold text-center mb-6">Welcome to SpecGuard</h2>
            
            <div className="flex border-b border-gray-200 mb-6">
              <button 
                onClick={() => { setIsLoginTab(true); setAuthError(""); setAuthSuccess(""); }}
                className={`flex-1 pb-3 text-center font-medium ${isLoginTab ? "border-b-2 border-indigo-600 text-indigo-600" : "text-gray-500 hover:text-gray-700"}`}
              >
                🔑 Login
              </button>
              <button 
                onClick={() => { setIsLoginTab(false); setAuthError(""); setAuthSuccess(""); }}
                className={`flex-1 pb-3 text-center font-medium ${!isLoginTab ? "border-b-2 border-indigo-600 text-indigo-600" : "text-gray-500 hover:text-gray-700"}`}
              >
                📝 Sign Up
              </button>
            </div>

            {authError && <div className="bg-red-50 text-red-700 p-3 rounded-lg border border-red-100 mb-4 text-sm">{authError}</div>}
            {authSuccess && <div className="bg-green-50 text-green-700 p-3 rounded-lg border border-green-100 mb-4 text-sm">{authSuccess}</div>}

            {isLoginTab ? (
              <form onSubmit={handleLogin} className="space-y-4">
                <div>
                  <label className="block text-xs font-bold text-gray-700 mb-1">Username or Email</label>
                  <input 
                    type="text" required
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none"
                    value={loginForm.username}
                    onChange={(e) => setLoginForm({ ...loginForm, username: e.target.value })}
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-gray-700 mb-1">Password</label>
                  <input 
                    type="password" required
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none"
                    value={loginForm.password}
                    onChange={(e) => setLoginForm({ ...loginForm, password: e.target.value })}
                  />
                </div>
                <button type="submit" className="w-full bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg py-2.5 font-medium transition text-sm">
                  Login
                </button>
              </form>
            ) : (
              <form onSubmit={handleRegister} className="space-y-4">
                <div>
                  <label className="block text-xs font-bold text-gray-700 mb-1">Full Legal Name *</label>
                  <input 
                    type="text" required
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500"
                    value={registerForm.fullName}
                    onChange={(e) => setRegisterForm({ ...registerForm, fullName: e.target.value })}
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-gray-700 mb-1">Department Email Address *</label>
                  <input 
                    type="email" required
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500"
                    value={registerForm.email}
                    onChange={(e) => setRegisterForm({ ...registerForm, email: e.target.value })}
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-gray-700 mb-1">Desired Username *</label>
                  <input 
                    type="text" required
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500"
                    value={registerForm.username}
                    onChange={(e) => setRegisterForm({ ...registerForm, username: e.target.value })}
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-gray-700 mb-1">Password *</label>
                  <input 
                    type="password" required
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500"
                    value={registerForm.password}
                    onChange={(e) => setRegisterForm({ ...registerForm, password: e.target.value })}
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-gray-700 mb-1">Confirm Password *</label>
                  <input 
                    type="password" required
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500"
                    value={registerForm.confirmPassword}
                    onChange={(e) => setRegisterForm({ ...registerForm, confirmPassword: e.target.value })}
                  />
                </div>
                <button type="submit" className="w-full bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg py-2.5 font-medium transition text-sm">
                  Register
                </button>
              </form>
            )}
          </div>
        )}

        {/* VIEW 2: PROFILE PAGE */}
        {currentPage === "Profile" && (
          <div className="max-w-xl bg-white rounded-xl border border-gray-200 shadow-sm p-8">
            <button 
              onClick={() => setCurrentPage("Dashboard")}
              className="text-indigo-600 hover:text-indigo-800 text-sm font-medium mb-6 flex items-center space-x-1"
            >
              <span>← Back to Dashboard</span>
            </button>
            <h2 className="text-2xl font-bold mb-6">👤 Personal Profile Settings</h2>
            
            {profileMsg.text && (
              <div className={`p-4 rounded-lg mb-6 text-sm border ${profileMsg.type === "success" ? "bg-green-50 border-green-200 text-green-700" : "bg-red-50 border-red-200 text-red-700"}`}>
                {profileMsg.text}
              </div>
            )}

            <form onSubmit={handleSaveProfile} className="space-y-4">
              <div>
                <label className="block text-xs font-bold text-gray-700 mb-1">Full Name</label>
                <input 
                  type="text" required
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500"
                  value={profileForm.fullName}
                  onChange={(e) => setProfileForm({ ...profileForm, fullName: e.target.value })}
                />
              </div>
              <div>
                <label className="block text-xs font-bold text-gray-700 mb-1">Email Address</label>
                <input 
                  type="email" required
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500"
                  value={profileForm.email}
                  onChange={(e) => setProfileForm({ ...profileForm, email: e.target.value })}
                />
              </div>
              <div>
                <label className="block text-xs font-bold text-gray-400 mb-1">System Role (Read-only)</label>
                <input 
                  type="text" disabled
                  className="w-full border border-gray-200 bg-gray-50 text-gray-400 rounded-lg px-3 py-2 text-sm"
                  value={user?.role || ""}
                />
              </div>
              <button type="submit" className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg px-6 py-2.5 text-sm font-medium transition">
                Save Changes
              </button>
            </form>
          </div>
        )}

        {/* VIEW 3: MAIN SYSTEM DASHBOARD */}
        {currentPage === "Dashboard" && (
          <div className="space-y-6">
            
            {/* INTERFACE TABS */}
            <div className="flex border-b border-gray-200">
              <button 
                onClick={() => setActiveTab("analysis")}
                className={`py-3 px-6 font-semibold text-sm border-b-2 transition ${activeTab === "analysis" ? "border-indigo-600 text-indigo-600" : "border-transparent text-gray-500 hover:text-gray-700"}`}
              >
                🔍 Analysis
              </button>
              <button 
                onClick={() => { setActiveTab("history"); fetchHistory(); }}
                className={`py-3 px-6 font-semibold text-sm border-b-2 transition ${activeTab === "history" ? "border-indigo-600 text-indigo-600" : "border-transparent text-gray-500 hover:text-gray-700"}`}
              >
                📜 History
              </button>
              {user?.role === "Admin" && (
                <button 
                  onClick={() => { setActiveTab("admin"); fetchPendingLogs(); }}
                  className={`py-3 px-6 font-semibold text-sm border-b-2 transition ${activeTab === "admin" ? "border-indigo-600 text-indigo-600" : "border-transparent text-gray-500 hover:text-gray-700"}`}
                >
                  👑 Admin Dashboard
                </button>
              )}
            </div>

            {/* TAB CONTENT: REQUIREMENT WORKSPACE */}
            {activeTab === "analysis" && (
              <div className="space-y-6">
                <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
                  <h3 className="text-lg font-bold mb-4">Requirement Analysis Workspace</h3>
                  
                  <div className="flex flex-col sm:flex-row items-stretch sm:items-center space-y-3 sm:space-y-0 sm:space-x-4">
                    <input 
                      type="file" 
                      accept=".pdf,.png,.jpg"
                      onChange={(e) => setSelectedFile(e.target.files[0])}
                      className="block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-indigo-50 file:text-indigo-700 hover:file:bg-indigo-100"
                    />
                    <button 
                      onClick={handleExtractText}
                      disabled={!selectedFile || isExtracting}
                      className="bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-300 text-white px-6 py-2 rounded-lg text-sm font-semibold transition"
                    >
                      {isExtracting ? "Extracting..." : "Extract Text"}
                    </button>
                  </div>
                </div>

                {extractedText && (
                  <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm space-y-4">
                    <h4 className="font-semibold text-gray-800">Extracted Text</h4>
                    <textarea 
                      readOnly
                      rows={6}
                      className="w-full border border-gray-200 bg-gray-50 rounded-lg p-3 text-sm font-mono text-gray-700 focus:outline-none"
                      value={extractedText}
                    />
                    <button 
                      onClick={handleRunAnalysis}
                      disabled={isAnalyzing}
                      className="w-full sm:w-auto bg-green-600 hover:bg-green-700 disabled:bg-gray-300 text-white px-8 py-3 rounded-lg text-sm font-bold transition shadow"
                    >
                      {isAnalyzing && (
                        <div className="flex items-center space-x-2 text-indigo-700 bg-indigo-50 p-4 border border-indigo-200 rounded-lg animate-pulse">
                          <span className="text-xl">⏳</span>
                          <p className="text-sm font-semibold">
                            {analysisProgress.total > 0 
                              ? `Analyzing requirement ${analysisProgress.current} of ${analysisProgress.total}...` 
                              : "Analyzing requirements..."}
                          </p>
                        </div>
                      )}
                    </button>
                  </div>
                )}

                {/* HORIZONTAL CARD ANALYSIS OUTPUT */}
                {analysisResults.length > 0 && (
                  <div className="space-y-6">
                    <div className="flex items-center space-x-2 text-green-700 bg-green-50 p-4 border border-green-200 rounded-lg">
                      <span className="text-xl">✨</span>
                      <p className="text-sm font-semibold">Batch audit of {analysisResults.length} requirement(s) completed!</p>
                    </div>

                    <div className="space-y-4">
                      {analysisResults.map((res, index) => (
                        <div key={index} className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
                          <div className="bg-gray-50 border-b border-gray-200 px-6 py-3 flex justify-between items-center">
                            <span className="font-bold text-sm text-indigo-600">✅ Requirement {index + 1} Analyzed</span>
                          </div>
                          
                          <div className="p-6 grid grid-cols-1 md:grid-cols-2 gap-6">
                            
                            {/* Column 1: Source Requirements */}
                            <div className="space-y-4">
                              <div>
                                <h5 className="text-xs font-extrabold tracking-wider text-gray-500 uppercase mb-2">❌ Original Requirement:</h5>
                                <div className="bg-blue-50 text-blue-800 px-4 py-3 rounded-lg border border-blue-100 text-sm inline-block max-w-full">
                                  {res.requirement}
                                </div>
                              </div>
                              <div className="pt-2">
                                <h5 className="text-xs font-extrabold tracking-wider text-gray-500 uppercase mb-1">📖 Matched Rule ({res.source_filename}):</h5>
                                <p className="text-xs text-gray-400 italic">
                                  {formatScannableClause(res.clause_text)}
                                </p>
                              </div>
                            </div>

                            {/* Column 2: Evaluative Framework */}
                            <div className="space-y-4 border-t md:border-t-0 md:border-l border-gray-100 pt-4 md:pt-0 md:pl-6">
                              <div>
                                <h5 className="text-xs font-extrabold tracking-wider text-gray-500 uppercase mb-2">🔍 AI Evaluation:</h5>
                                <p className="text-sm text-gray-700 whitespace-pre-line bg-gray-50 p-3 rounded-lg border border-gray-150">
                                  {res.analysis}
                                </p>
                              </div>
                              <div>
                                <h5 className="text-xs font-extrabold tracking-wider text-gray-500 uppercase mb-2">Suggested Rewrite:</h5>
                                <div className="bg-green-50 text-green-800 px-4 py-3 rounded-lg border border-green-100 text-sm inline-block max-w-full font-medium">
                                  {res.suggested_rewrite}
                                </div>
                              </div>
                            </div>

                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* TAB CONTENT: DOCUMENT HISTORY */}
            {activeTab === "history" && (
              <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
                <h3 className="text-lg font-bold mb-1">Document History</h3>
                <p className="text-sm text-gray-500 mb-6">View past submitted requirements and their verified results.</p>
                
                {historyList.length === 0 ? (
                  <div className="text-center py-12 text-gray-400 border border-dashed border-gray-200 rounded-lg">
                    No history records available yet.
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-left border-collapse">
                      <thead>
                        <tr className="border-b border-gray-200 text-xs font-extrabold uppercase text-gray-400 tracking-wider">
                          <th className="pb-3 pl-4">Date Processed</th>
                          <th className="pb-3 px-4">Target Requirement</th>
                          <th className="pb-3 px-4">Status</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-100 text-sm text-gray-700">
                        {historyList.map((item, index) => (
                          <tr key={index} className="hover:bg-gray-50">
                            <td className="py-4 pl-4 whitespace-nowrap text-gray-500">{item.timestamp}</td>
                            <td className="py-4 px-4 font-mono text-xs max-w-md truncate">{item.requirement}</td>
                            <td className="py-4 px-4">
                              <span className={`px-2.5 py-1 rounded-full text-xs font-semibold ${item.status === "Validated" ? "bg-green-100 text-green-800" : "bg-yellow-100 text-yellow-800"}`}>
                                {item.status}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            {/* TAB CONTENT: ADMIN DEPLOYMENT PORTAL */}
            {activeTab === "admin" && (
              <div className="space-y-6">
                <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
                  <h3 className="text-lg font-bold mb-1">Admin Validation Hub</h3>
                  <h4 className="text-sm font-semibold text-indigo-600">Data Flywheel Curation Matrix</h4>
                  <p className="text-xs text-gray-400 mt-2">
                    📥 Found {pendingLogs.length} pending transaction(s) awaiting validation.
                  </p>
                </div>

                <div className="space-y-4">
                  {pendingLogs.map((log) => {
                    const isExpanded = expandedLogId === log.id;
                    const valText = editedOutputs[log.id] !== undefined ? editedOutputs[log.id] : log.model_output;
                    
                    return (
                      <div key={log.id} className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
                        <div 
                          onClick={() => setExpandedLogId(isExpanded ? null : log.id)}
                          className="px-6 py-4 flex justify-between items-center hover:bg-gray-50 cursor-pointer transition select-none"
                        >
                          <div className="flex flex-col sm:flex-row sm:items-center space-y-1 sm:space-y-0 sm:space-x-3 text-sm">
                            <span className="font-bold text-gray-700">🔹 Log #{log.id}</span>
                            <span className="text-gray-400">|</span>
                            <span className="text-gray-500 font-mono text-xs">{log.timestamp}</span>
                            <span className="text-gray-400 hidden sm:inline">|</span>
                            <span className="truncate text-gray-600 font-semibold max-w-xs sm:max-w-md">
                              {log.requirement}
                            </span>
                          </div>
                          <span className="text-gray-400">{isExpanded ? "▲" : "▼"}</span>
                        </div>

                        {isExpanded && (
                          <div className="px-6 pb-6 pt-2 border-t border-gray-100 space-y-4">
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                              <div>
                                <label className="block text-xs font-bold text-red-700 mb-1">❌ Original Requirement:</label>
                                <textarea readOnly rows={3} value={log.requirement} className="w-full text-xs bg-gray-50 border border-gray-200 rounded-lg p-2.5 focus:outline-none" />
                              </div>
                              <div>
                                <label className="block text-xs font-bold text-gray-700 mb-1">📖 Matched Rule:</label>
                                <textarea readOnly rows={3} value={log.matched_rule} className="w-full text-xs bg-gray-50 border border-gray-200 rounded-lg p-2.5 focus:outline-none" />
                              </div>
                            </div>

                            <div>
                              <label className="block text-xs font-bold text-gray-700 mb-1">Model Evaluation Output (Editable for Ground Truth):</label>
                              <textarea 
                                rows={6} 
                                value={valText}
                                onChange={(e) => setEditedOutputs({ ...editedOutputs, [log.id]: e.target.value })}
                                className="w-full text-xs border border-gray-300 rounded-lg p-3 font-mono focus:ring-2 focus:ring-indigo-500" 
                              />
                            </div>

                            <div className="flex space-x-3 justify-end pt-2">
                              <button 
                                onClick={() => handleDeleteLog(log.id)}
                                className="px-4 py-2 bg-red-100 hover:bg-red-200 text-red-700 text-xs font-bold rounded-lg transition"
                              >
                                🗑️ Reject & Delete Log
                              </button>
                              <button 
                                onClick={() => handleApproveLog(log.id)}
                                className="px-5 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-bold rounded-lg transition shadow-sm"
                              >
                                ✅ Approve & Export for Training
                              </button>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

          </div>
        )}

      </main>
    </div>
  );
}