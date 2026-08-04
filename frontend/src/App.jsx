import { useState, useEffect } from 'react';

const API_BASE = "http://localhost:8000/api";

export default function App() {
  // Session & UI Navigation State (Resets to Welcome on every relaunch)
  const [user, setUser] = useState(null);
  const [currentPage, setCurrentPage] = useState("Welcome");
  const [activeTab, setActiveTab] = useState("portal"); 
  const [showProfileDropdown, setShowProfileDropdown] = useState(false);
  const [showNotificationsDropdown, setShowNotificationsDropdown] = useState(false);
  
  // Auth Modals State (Login, Register, or null)
  const [authModal, setAuthModal] = useState(null);

  // Authentication States
  const [loginForm, setLoginForm] = useState({ username: "", password: "" });
  const [registerForm, setRegisterForm] = useState({ username: "", password: "", fullName: "", email: "", role: "User", phone_number: "", company_name: "", confirmPassword: "" });
  const [authError, setAuthError] = useState("");
  const [authSuccess, setAuthSuccess] = useState("");

  // Standard User Analysis States
  const [selectedFile, setSelectedFile] = useState(null);
  const [isExtracting, setIsExtracting] = useState(false);
  const [extractedText, setExtractedText] = useState("");
  const [documentName, setDocumentName] = useState("Untitled Specification");
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analysisResults, setAnalysisResults] = useState([]);
  const [analysisProgress, setAnalysisProgress] = useState({ current: 0, total: 0 });
  
  // Grouped User History States
  const [historyList, setHistoryList] = useState([]);
  const [expandedUserHistDocId, setExpandedUserHistDocId] = useState(null);
  const [expandedUserHistReqId, setExpandedUserHistReqId] = useState(null);

  // User Notification States
  const [notifications, setNotifications] = useState([]);
  const [activeComparison, setActiveComparison] = useState(null);

  // Domain Expert States
  const [expertQueue, setExpertQueue] = useState([]);
  const [expertHistory, setExpertHistory] = useState([]);
  const [expandedDocId, setExpandedDocId] = useState(null);
  const [expertActiveReqs, setExpertActiveReqs] = useState([]);
  const [expertEdits, setExpertEdits] = useState({}); 
  
  // Expert History States
  const [expandedExpertHistDocId, setExpandedExpertHistDocId] = useState(null);
  const [expertHistoryReqs, setExpertHistoryReqs] = useState([]);

  // Comprehensive Admin Console State
  const [adminLogsData, setAdminLogsData] = useState({ pending: [], locked: [], approved: [], rejected: [] });

  // Profile Edit
  const [profileForm, setProfileForm] = useState({ fullName: "", email: "", phoneNumber: "", companyName: "", newPassword: "" });
  const [profileMsg, setProfileMsg] = useState({ type: "", text: "" });

  // Click outside to close dropdowns
  useEffect(() => {
    const handleOutsideClick = () => {
      setShowProfileDropdown(false);
      setShowNotificationsDropdown(false);
    };
    document.addEventListener("click", handleOutsideClick);
    return () => document.removeEventListener("click", handleOutsideClick);
  }, []);

  const refreshCoreData = () => {
    if (!user) return;
    if (user.role === "User") {
      fetchHistory();
      fetchNotifications();
    } else if (user.role === "Expert") {
      fetchExpertQueueList();
      fetchExpertHistoryList();
    } else if (user.role === "Admin") {
      fetchAdminAllLogs();
    }
  };

  const fetchProfileData = async () => {
    try {
      const res = await fetch(`${API_BASE}/profile/${user.username}`);
      if (res.ok) {
        const data = await res.json();
        setProfileForm({
          fullName: data.full_name,
          email: data.email,
          phoneNumber: data.phone_number || "",
          companyName: data.company_name || "",
          newPassword: ""
        });
      }
    } catch (e) { console.error(e); }
  };

  // Base API Implementations
  const fetchHistory = async () => {
    try {
      const res = await fetch(`${API_BASE}/history/${user.username}`);
      if (res.ok) setHistoryList(await res.json());
    } catch (e) { console.error(e); }
  };

  const fetchNotifications = async () => {
    try {
      const res = await fetch(`${API_BASE}/notifications/${user.username}`);
      if (res.ok) setNotifications(await res.json());
    } catch (e) { console.error(e); }
  };

  const fetchAdminAllLogs = async () => {
    try {
      const res = await fetch(`${API_BASE}/admin/all-logs`);
      if (res.ok) setAdminLogsData(await res.json());
    } catch (e) { console.error(e); }
  };

  const handleAdminDelete = async (log) => {
    const datasetWarning = log.lifecycle_status === "APPROVED"
      ? " This will also remove its exported training record."
      : "";
    if (!confirm(`Delete requirement #${log.id}?${datasetWarning}`)) return;
    try {
      const res = await fetch(`${API_BASE}/admin/logs/${log.id}`, { method: "DELETE" });
      if (res.ok) {
        fetchAdminAllLogs();
      } else {
        const error = await res.json();
        alert(error.detail?.code || "Unable to delete this requirement.");
      }
    } catch (e) { console.error(e); }
  };

  const handleAdminDeleteDocument = async (log) => {
    const datasetWarning = log.lifecycle_status === "APPROVED"
      ? " All exported training records for this document will also be removed."
      : "";
    if (!confirm(`Delete the entire document '${log.document_name}'?${datasetWarning}`)) return;
    try {
      const res = await fetch(`${API_BASE}/admin/documents/${log.document_id}`, { method: "DELETE" });
      if (res.ok) {
        fetchAdminAllLogs();
      } else {
        const error = await res.json();
        alert(error.detail?.code || "Unable to delete this document.");
      }
    } catch (e) { console.error(e); }
  };

  // Auth Functions
  const handleLogin = async (e) => {
    e.preventDefault();
    setAuthError("");
    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(loginForm)
      });
      const data = await res.json();
      if (res.ok) {
        setUser(data);
        setAuthModal(null);
        setActiveTab("portal"); 
        setCurrentPage("Dashboard");
      } else {
        setAuthError(data.detail || "Authentication failure.");
      }
    } catch { setAuthError("Cannot establish connection to server."); }
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
          email: registerForm.email,
          role: registerForm.role,
          phone_number: registerForm.phone_number,
          company_name: registerForm.company_name
        })
      });
      const data = await res.json();
      if (res.ok) {
        setAuthSuccess("Account successfully established! Proceed to Login.");
        setAuthModal("Login");
      } else {
        setAuthError(data.detail || "Registration failed.");
      }
    } catch { setAuthError("Network connection timeout."); }
  };

  const handleLogout = () => {
    setUser(null);
    setCurrentPage("Welcome");
  };

  // Real-time Streaming Uploads
  const handleExtractText = async () => {
    if (!selectedFile) return;
    setIsExtracting(true);
    const formData = new FormData();
    formData.append("file", selectedFile);
    try {
      const res = await fetch(`${API_BASE}/analysis/upload`, { method: "POST", body: formData });
      const data = await res.json();
      if (res.ok) {
        setExtractedText(data.extracted_text);
        setDocumentName(selectedFile.name);
        setAnalysisResults([]);
      } else {
        alert(data.detail || "Extraction failed.");
      }
    } catch { alert("File upload exception."); }
    finally { setIsExtracting(false); }
  };

  const handleRunAnalysis = async () => {
    if (!extractedText.trim()) return;
    setIsAnalyzing(true);
    setAnalysisResults([]);
    setAnalysisProgress({ current: 0, total: 0 });

    try {
      const response = await fetch(`${API_BASE}/analysis/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: user.username, raw_text: extractedText, document_name: documentName })
      });

      if (!response.ok) {
        alert("Verification pipeline failure.");
        setIsAnalyzing(false);
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop();

        for (const line of lines) {
          if (line.trim() === "") continue;
          try {
            const chunk = JSON.parse(line);
            if (chunk.type === "empty") {
              alert(chunk.message);
            } else if (chunk.type === "result") {
              setAnalysisResults((prev) => [...prev, chunk.data]);
              setAnalysisProgress(chunk.progress);
            }
          } catch (e) { console.error(e); }
        }
      }
      fetchHistory();
    } catch { alert("Network disconnect during batch execution."); }
    finally { setIsAnalyzing(false); }
  };

  // Domain Expert Core logic
  const fetchExpertQueueList = async () => {
    try {
      const res = await fetch(`${API_BASE}/expert/queue?expert_username=${user.username}`);
      if (res.ok) setExpertQueue(await res.json());
    } catch (e) { console.error(e); }
  };

  const fetchExpertHistoryList = async () => {
    try {
      const res = await fetch(`${API_BASE}/expert/history/${user.username}`);
      if (res.ok) setExpertHistory(await res.json());
    } catch (e) { console.error(e); }
  };

  const handleClaimDocument = async (documentId) => {
    const activeDocument = expertQueue.find(
      doc => doc.lifecycle_status === "LOCKED" && doc.assigned_expert === user.username
    );
    if (activeDocument && activeDocument.document_id !== documentId) {
      alert(`Finish or release '${activeDocument.document_name}' before claiming another document.`);
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/expert/lock`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ document_id: documentId, expert_username: user.username })
      });
      if (res.ok) {
        fetchExpertQueueList();
        handleExpandDocument(documentId);
      } else {
        const err = await res.json();
        const detail = err.detail;
        if (detail?.code === "ACTIVE_LOCK_EXISTS") {
          alert(`Finish or release '${detail.document_name}' before claiming another document.`);
        } else {
          alert("This document is no longer available for review.");
        }
      }
    } catch (e) { console.error(e); }
  };

  const handleUnlockDocument = async (documentId) => {
    if (!confirm("Return this document set back to the pending queue for other experts?")) return;
    try {
      const res = await fetch(`${API_BASE}/expert/unlock`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ document_id: documentId, expert_username: user.username })
      });
      if (res.ok) {
        setExpandedDocId(null);
        setExpertActiveReqs([]);
        fetchExpertQueueList();
      } else {
        alert("Failed to release lock.");
      }
    } catch (e) { console.error(e); }
  };

  const handleExpandDocument = async (documentId) => {
    if (expandedDocId === documentId) {
      setExpandedDocId(null);
      setExpertActiveReqs([]);
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/expert/requirements/${documentId}?expert_username=${encodeURIComponent(user.username)}`);
      if (res.ok) {
        const reqs = await res.json();
        setExpertActiveReqs(reqs);
        setExpandedDocId(documentId);
        
        // Pre-fill editable outputs using AI evaluations
        const initialEdits = {};
        reqs.forEach(r => {
          const parsed = parseModelOutput(r.model_output);
          initialEdits[r.id] = {
            expert_evaluation: r.expert_evaluation || parsed.analysis,
            expert_rewrite: r.expert_rewrite || parsed.rewrite
          };
        });
        setExpertEdits(initialEdits);
      }
    } catch (e) { console.error(e); }
  };

  // Detailed Viewer for Expert Submitted Audits
  const handleExpandExpertHistory = async (documentId) => {
    if (expandedExpertHistDocId === documentId) {
      setExpandedExpertHistDocId(null);
      setExpertHistoryReqs([]);
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/expert/requirements/${documentId}?expert_username=${encodeURIComponent(user.username)}`);
      if (res.ok) {
        setExpertHistoryReqs(await res.json());
        setExpandedExpertHistDocId(documentId);
      }
    } catch (e) { console.error(e); }
  };

  const handleUpdateEditField = (reqId, field, value) => {
    setExpertEdits(prev => ({
      ...prev,
      [reqId]: {
        ...prev[reqId],
        [field]: value
      }
    }));
  };

  const handleSubmitExpertAudit = async (documentId, isApproved) => {
    const reviewsPayload = expertActiveReqs.map(r => ({
      id: r.id,
      expert_evaluation: expertEdits[r.id]?.expert_evaluation || "",
      expert_rewrite: expertEdits[r.id]?.expert_rewrite || ""
    }));

    try {
      const res = await fetch(`${API_BASE}/expert/submit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          document_id: documentId,
          expert_username: user.username,
          reviews: reviewsPayload,
          is_approved: isApproved
        })
      });
      if (res.ok) {
        alert(isApproved ? "Human-verified dataset exported." : "Document rejected and retained for audit history.");
        setExpandedDocId(null);
        setExpertActiveReqs([]);
        fetchExpertQueueList();
        fetchExpertHistoryList();
      } else {
        alert("Failed to process expert review.");
      }
    } catch (e) { console.error(e); }
  };

  // Comparative Notifications View
  const handleOpenComparison = async (notif) => {
    try {
      const res = await fetch(`${API_BASE}/notifications/${user.username}/compare/${notif.document_id}`);
      if (res.ok) {
        const data = await res.json();
        setActiveComparison({
          documentName: notif.document_name,
          expertUsername: notif.expert_username,
          comparisons: data
        });
        
        // Mark notification as read
        await fetch(`${API_BASE}/notifications/${notif.id}/read`, { method: "POST" });
        fetchNotifications();
      }
    } catch (e) { console.error(e); }
  };

  const handleDeleteNotification = async (notificationId, e) => {
    e.stopPropagation(); // Stop click from triggering 'handleOpenComparison' modal
    try {
      const res = await fetch(`${API_BASE}/notifications/${notificationId}`, { method: "DELETE" });
      if (res.ok) {
        setNotifications((prev) => prev.filter(n => n.id !== notificationId));
      }
    } catch (err) { console.error(err); }
  };

  // Profile Edit Form Submit
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
          email: profileForm.email,
          phone_number: profileForm.phoneNumber,
          company_name: profileForm.companyName,
          password: profileForm.newPassword
        })
      });
      if (res.ok) {
        const updatedUser = { ...user, full_name: profileForm.fullName, email: profileForm.email };
        setUser(updatedUser);
        setProfileMsg({ type: "success", text: "Profile details saved successfully." });
      } else {
        setProfileMsg({ type: "error", text: "An error occurred while updating profile." });
      }
    } catch { setProfileMsg({ type: "error", text: "Connection error." }); }
  };

  // Helper grouping functions for User History Drill-downs
  const getGroupedUserHistory = () => {
    const groups = {};
    historyList.forEach(item => {
      const docId = item.document_id || "single_sentences";
      const docName = item.document_name || "Single Sentences / Untagged";
      if (!groups[docId]) {
        groups[docId] = {
          document_id: docId,
          document_name: docName,
          timestamp: item.timestamp,
          items: []
        };
      }
      groups[docId].items.push(item);
    });
    return Object.values(groups);
  };

  const parseModelOutput = (output) => {
    let analysis = output;
    let rewrite = "No rewrite suggested.";
    if (output && output.includes("### Suggested Rewrite")) {
      const parts = output.split("### Suggested Rewrite");
      analysis = parts[0].replace("### Analysis", "").trim();
      rewrite = parts[1].trim();
    }
    return { analysis, rewrite };
  };

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (user) {
      fetchProfileData();
      refreshCoreData();
    }
    // These request helpers intentionally refresh whenever the active role tab changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, activeTab]);
  /* eslint-enable react-hooks/set-state-in-effect */

  return (
    <div className="min-h-screen bg-gray-50 text-gray-800 flex flex-col font-sans">
      
      {/* 🛡️ HEADER SECTION */}
      <header className="bg-white border-b border-gray-200 px-6 py-4 flex justify-between items-center sticky top-0 z-50 shadow-sm">
        <div className="flex items-center space-x-2">
          <span className="text-3xl" role="img" aria-label="shield">🛡️</span>
          <h1 className="text-2xl font-black text-indigo-600 dark:text-indigo-400 tracking-tight">SpecGuard</h1>
        </div>

        <div className="flex items-center space-x-4">
          {user ? (
            <>
              {/* Notification Bell (Only for standard Users) */}
              {user.role === "User" && (
                <div className="relative" onClick={(e) => e.stopPropagation()}>
                  <button 
                    onClick={() => { setShowNotificationsDropdown(!showNotificationsDropdown); setShowProfileDropdown(false); }}
                    className="relative p-2 text-gray-500 hover:text-indigo-600 hover:bg-gray-100 rounded-lg transition focus:outline-none"
                  >
                    <span className="text-xl">🔔</span>
                    {notifications.filter(n => !n.is_read).length > 0 && (
                      <span className="absolute top-1 right-1 bg-red-500 text-white text-[9px] px-1.5 py-0.5 rounded-full font-bold">
                        {notifications.filter(n => !n.is_read).length}
                      </span>
                    )}
                  </button>
                  {showNotificationsDropdown && (
                    <div className="absolute right-0 mt-2 w-80 bg-white border border-gray-200 rounded-lg shadow-lg py-3 z-50 animate-fade-in max-h-96 overflow-y-auto">
                      <div className="px-4 pb-2 border-b border-gray-100 text-xs font-bold text-gray-500 flex justify-between items-center">
                        <span>Expert Alerts Centre</span>
                        {notifications.length > 0 && <span className="text-[10px] bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded-full">{notifications.length} total</span>}
                      </div>
                      <div className="divide-y divide-gray-50">
                        {notifications.map(n => {
                          return (
                            <div key={n.id} className={`p-4 text-xs space-y-2 hover:bg-gray-50 transition relative group ${n.is_read ? "" : "bg-blue-50/30"}`}>
                              <button 
                                onClick={(e) => handleDeleteNotification(n.id, e)}
                                className="absolute top-3 right-3 text-gray-400 hover:text-red-500 font-black text-[11px] focus:outline-none transition opacity-100 md:opacity-0 group-hover:opacity-100"
                                title="Dismiss Alert"
                              >
                                ✕
                              </button>
                              <p className="font-semibold text-gray-800 pr-4">{n.document_name}</p>
                              <p className="text-gray-500 leading-relaxed pr-4">{n.message}</p>
                              <button 
                                onClick={() => { handleOpenComparison(n); setShowNotificationsDropdown(false); }}
                                className="text-indigo-600 hover:text-indigo-800 font-bold block"
                              >
                                View Improvements →
                              </button>
                            </div>
                          );
                        })}
                        {notifications.length === 0 && (
                          <div className="text-center py-8 text-gray-400">No new alerts.</div>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Profile dropdown */}
              <div className="relative" onClick={(e) => e.stopPropagation()}>
                <button 
                  onClick={() => { setShowProfileDropdown(!showProfileDropdown); setShowNotificationsDropdown(false); }}
                  className="bg-gray-100 hover:bg-gray-200 text-gray-700 px-4 py-2 rounded-lg flex items-center space-x-2 border border-gray-200 transition focus:outline-none"
                >
                  <span>👤</span>
                  <span className="font-semibold text-sm">{user.full_name}</span>
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
            </>
          ) : (
            <div className="space-x-2">
              <button onClick={() => { setAuthModal("Login"); setAuthError(""); setAuthSuccess(""); }} className="text-gray-600 hover:text-indigo-600 font-semibold text-sm px-4 py-2 rounded-lg hover:bg-gray-100 transition">
                Login
              </button>
              <button onClick={() => { setAuthModal("Register"); setAuthError(""); setAuthSuccess(""); }} className="bg-indigo-600 hover:bg-indigo-700 text-white font-bold text-sm px-4 py-2 rounded-lg transition shadow-sm">
                Sign Up
              </button>
            </div>
          )}
        </div>
      </header>

      {/* FIXED METRIC DIVIDER BAR */}
      <hr className="border-t border-gray-200" style={{ margin: "-25px 0px 15px 0px" }} />

      {/* FULL-WIDTH CANVAS CONTAINER */}
      <main className="flex-grow p-6 w-full max-w-none">
        
        {/* WELCOME / LANDING SCREEN */}
        {currentPage === "Welcome" && (
          <div className="space-y-12 py-6 animate-fade-in max-w-6xl mx-auto">
            <div className="text-center space-y-4">
              <h2 className="text-4xl font-extrabold tracking-tight text-gray-950 sm:text-5xl">🛡️ Automated Requirements Audit Engine</h2>
              <p className="text-lg text-gray-500 max-w-2xl mx-auto">
                SpecGuard uses specialized local Large Language Models and semantic rule retrieval to analyze specification documents, detect drafting defects, and generate corrected standards.
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div className="bg-white border border-gray-200 rounded-2xl p-6 shadow-sm space-y-3">
                <span className="text-3xl">📉</span>
                <h3 className="text-base font-bold text-gray-900">The Requirement Ambiguity Cost</h3>
                <p className="text-xs text-gray-500 leading-relaxed">
                  Requirement errors represent over 40% of standard software engineering defects. Finding and resolving specification gaps during the design layer is up to 100 times cheaper than patching compiled production systems.
                </p>
              </div>
              <div className="bg-white border border-gray-200 rounded-2xl p-6 shadow-sm space-y-3">
                <span className="text-3xl">🔍</span>
                <h3 className="text-base font-bold text-gray-900">Semantic RAG Compliance</h3>
                <p className="text-xs text-gray-500 leading-relaxed">
                  The platform isolates target compliance statements containing key keywords (shall, must, will) and queries vector indexes using BGE-M3 to map rules directly beside candidate requirements.
                </p>
              </div>
              <div className="bg-white border border-gray-200 rounded-2xl p-6 shadow-sm space-y-3">
                <span className="text-3xl">🔄</span>
                <h3 className="text-base font-bold text-gray-900">Staging Data Flywheel</h3>
                <p className="text-xs text-gray-500 leading-relaxed">
                  By employing Domain Experts to curate and override raw AI evaluations, SpecGuard logs human-verified Ground Truths into instruction-response datasets to continuously retrain and adapt local weights.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* AUTHENTICATION MODAL POPUP */}
        {authModal && (
          <div className="fixed inset-0 bg-gray-950/40 backdrop-blur-sm z-50 flex items-center justify-center p-4 animate-fade-in" onClick={() => setAuthModal(null)}>
            <div className="bg-white border border-gray-200 rounded-2xl shadow-xl p-8 max-w-md w-full space-y-6 relative" onClick={(e) => e.stopPropagation()}>
              <button onClick={() => setAuthModal(null)} className="absolute top-4 right-4 text-gray-400 hover:text-gray-600 text-lg font-black focus:outline-none">✕</button>
              
              <h2 className="text-2xl font-bold text-gray-950">{authModal} Portal</h2>

              {authError && <div className="bg-red-50 text-red-700 p-3 rounded-lg border border-red-100 text-xs">{authError}</div>}
              {authSuccess && <div className="bg-green-50 text-green-700 p-3 rounded-lg border border-green-100 text-xs">{authSuccess}</div>}

              {authModal === "Login" ? (
                <form onSubmit={handleLogin} className="space-y-4">
                  <div>
                    <label className="block text-xs font-bold text-gray-700 mb-1">Username or Email</label>
                    <input type="text" required value={loginForm.username} onChange={(e) => setLoginForm({ ...loginForm, username: e.target.value })} className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none" />
                  </div>
                  <div>
                    <label className="block text-xs font-bold text-gray-700 mb-1">Password</label>
                    <input type="password" required value={loginForm.password} onChange={(e) => setLoginForm({ ...loginForm, password: e.target.value })} className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none" />
                  </div>
                  <button type="submit" className="w-full bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg py-2.5 font-bold transition text-sm">Login</button>
                </form>
              ) : (
                <form onSubmit={handleRegister} className="space-y-4 max-h-[450px] overflow-y-auto pr-1">
                  <div>
                    <label className="block text-xs font-bold text-gray-700 mb-1">Full Name *</label>
                    <input type="text" required value={registerForm.fullName} onChange={(e) => setRegisterForm({ ...registerForm, fullName: e.target.value })} className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm" />
                  </div>
                  <div>
                    <label className="block text-xs font-bold text-gray-700 mb-1">Email Address *</label>
                    <input type="email" required value={registerForm.email} onChange={(e) => setRegisterForm({ ...registerForm, email: e.target.value })} className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm" />
                  </div>
                  <div>
                    <label className="block text-xs font-bold text-gray-700 mb-1">Phone Number</label>
                    <input type="text" value={registerForm.phone_number} onChange={(e) => setRegisterForm({ ...registerForm, phone_number: e.target.value })} className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none" />
                  </div>
                  <div>
                    <label className="block text-xs font-bold text-gray-700 mb-1">Company Name</label>
                    <input type="text" value={registerForm.company_name} onChange={(e) => setRegisterForm({ ...registerForm, company_name: e.target.value })} className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none" />
                  </div>
                  <div>
                    <label className="block text-xs font-bold text-gray-700 mb-1">Username *</label>
                    <input type="text" required value={registerForm.username} onChange={(e) => setRegisterForm({ ...registerForm, username: e.target.value })} className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm" />
                  </div>
                  <div>
                    <label className="block text-xs font-bold text-gray-700 mb-1">Role Type *</label>
                    <select value={registerForm.role} onChange={(e) => setRegisterForm({ ...registerForm, role: e.target.value })} className="w-full border border-gray-300 bg-white rounded-lg px-3 py-2 text-sm">
                      <option value="User">Standard User</option>
                      <option value="Expert">Domain Expert</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs font-bold text-gray-700 mb-1">Password *</label>
                    <input type="password" required value={registerForm.password} onChange={(e) => setRegisterForm({ ...registerForm, password: e.target.value })} className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm" />
                  </div>
                  <div>
                    <label className="block text-xs font-bold text-gray-700 mb-1">Confirm Password *</label>
                    <input type="password" required value={registerForm.confirmPassword} onChange={(e) => setRegisterForm({ ...registerForm, confirmPassword: e.target.value })} className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm" />
                  </div>
                  <button type="submit" className="w-full bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg py-2.5 font-medium transition text-sm">Register</button>
                </form>
              )}
            </div>
          </div>
        )}

        {/* VIEW 2: PROFILE PROFILE SETTINGS (Centered in the viewport) */}
        {currentPage === "Profile" && (
          <div className="max-w-xl mx-auto bg-white rounded-xl border border-gray-200 shadow-sm p-8 my-6">
            <button onClick={() => setCurrentPage("Dashboard")} className="text-indigo-600 hover:text-indigo-800 text-sm font-medium mb-6 flex items-center space-x-1">
              <span>← Back to Dashboard</span>
            </button>
            <h2 className="text-2xl font-bold mb-6 text-gray-900 border-b border-gray-100 pb-3">👤 Personal Profile Settings</h2>
            
            {profileMsg.text && (
              <div className={`p-4 rounded-lg mb-6 text-sm border ${profileMsg.type === "success" ? "bg-green-50 border-green-200 text-green-700" : "bg-red-50 border-red-200 text-red-700"}`}>
                {profileMsg.text}
              </div>
            )}

            <form onSubmit={handleSaveProfile} className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-bold text-gray-700 mb-1">Full Name</label>
                  <input type="text" required value={profileForm.fullName} onChange={(e) => setProfileForm({ ...profileForm, fullName: e.target.value })} className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm" />
                </div>
                <div>
                  <label className="block text-xs font-bold text-gray-700 mb-1">Email Address</label>
                  <input type="email" required value={profileForm.email} onChange={(e) => setProfileForm({ ...profileForm, email: e.target.value })} className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm" />
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-bold text-gray-700 mb-1">Phone Number</label>
                  <input type="text" value={profileForm.phoneNumber} onChange={(e) => setProfileForm({ ...profileForm, phoneNumber: e.target.value })} className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none" />
                </div>
                <div>
                  <label className="block text-xs font-bold text-gray-700 mb-1">Company Name</label>
                  <input type="text" value={profileForm.companyName} onChange={(e) => setProfileForm({ ...profileForm, companyName: e.target.value })} className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none" />
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-bold text-gray-400 mb-1">System Role (Read-only)</label>
                  <input type="text" disabled value={user?.role || ""} className="w-full border border-gray-200 bg-gray-50 text-gray-400 rounded-lg px-3 py-2 text-sm focus:outline-none" />
                </div>
                <div>
                  <label className="block text-xs font-bold text-gray-700 mb-1">Update Password (Optional)</label>
                  <input type="password" placeholder="Leave blank to keep current" value={profileForm.newPassword} onChange={(e) => setProfileForm({ ...profileForm, newPassword: e.target.value })} className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none" />
                </div>
              </div>

              <div className="pt-2">
                <button type="submit" className="w-full bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg py-2.5 text-sm font-semibold transition shadow-sm">
                  Save Changes
                </button>
              </div>
            </form>
          </div>
        )}

        {/* VIEW 3: SYSTEM DASHBOARD */}
        {currentPage === "Dashboard" && (
          <div className="space-y-6">

            {/* ROLE: STANDARD USER */}
            {user?.role === "User" && (
              <div className="space-y-6">
                
                {/* DUAL-CARD PORTAL MENU LANDING SCREEN */}
                {activeTab === "portal" && (
                  <div className="space-y-8 animate-fade-in py-4 max-w-5xl mx-auto">
                    <div className="bg-gradient-to-r from-indigo-50 to-blue-50 border border-indigo-100 rounded-2xl p-8 shadow-sm">
                      <h3 className="text-2xl font-black text-indigo-950">Welcome back, {user.full_name}!</h3>
                      <p className="text-sm text-indigo-700/80 mt-2">Select a workspace operation from the control hub below to start compliance auditing.</p>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                      {/* Card 1: Run Analysis */}
                      <div className="bg-white border border-gray-200 rounded-2xl p-8 hover:border-indigo-200 hover:shadow-md transition group">
                        <span className="text-4xl block mb-4">🔍</span>
                        <h4 className="text-lg font-bold text-gray-900 group-hover:text-indigo-600 transition">Requirement Analysis Workspace</h4>
                        <p className="text-xs text-gray-500 leading-relaxed mt-2 mb-6">
                          Upload project specification files (.pdf, .png, .jpg), trigger localized OCR text extraction layers, and execute real-time compliance checks.
                        </p>
                        <button onClick={() => { setActiveTab("analysis"); setExtractedText(""); setAnalysisResults([]); }} className="bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-bold px-6 py-2.5 rounded-xl transition shadow-sm">
                          ▶ Start Analysis
                        </button>
                      </div>

                      {/* Card 2: View History */}
                      <div className="bg-white border border-gray-200 rounded-2xl p-8 hover:border-indigo-200 hover:shadow-md transition group">
                        <span className="text-4xl block mb-4">📜</span>
                        <h4 className="text-lg font-bold text-gray-900 group-hover:text-indigo-600 transition">Historical Audit Log</h4>
                        <p className="text-xs text-gray-500 leading-relaxed mt-2 mb-6">
                          Review structured evaluation records grouped by file name, expand sentence targets, and inspect prior standard matching reports.
                        </p>
                        <button onClick={() => { setActiveTab("history"); fetchHistory(); }} className="bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-bold px-6 py-2.5 rounded-xl transition shadow-sm">
                          📜 View History
                        </button>
                      </div>
                    </div>
                  </div>
                )}

                {/* USER TAB: COMPLIANCE ANALYSIS */}
                {activeTab === "analysis" && (
                  <div className="space-y-6">
                    <div className="flex justify-between items-center bg-white rounded-xl border border-gray-200 px-6 py-4 shadow-sm">
                      <button onClick={() => setActiveTab("portal")} className="text-indigo-600 hover:text-indigo-800 text-sm font-bold flex items-center space-x-1 focus:outline-none">
                        <span>← Back to Portal</span>
                      </button>
                      <h3 className="text-sm font-bold text-gray-700">Analysis Workspace</h3>
                    </div>

                    <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
                      <h3 className="text-lg font-bold mb-4">Requirement Analysis Workspace</h3>
                      <div className="flex flex-col sm:flex-row items-stretch sm:items-center space-y-3 sm:space-y-0 sm:space-x-4">
                        <input type="file" accept=".pdf,.png,.jpg" onChange={(e) => setSelectedFile(e.target.files[0])} className="block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-indigo-50 file:text-indigo-700 hover:file:bg-indigo-100" />
                        <button onClick={handleExtractText} disabled={!selectedFile || isExtracting} className="bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-300 text-white px-6 py-2 rounded-lg text-sm font-semibold transition">
                          {isExtracting ? "Extracting..." : "Extract Text"}
                        </button>
                      </div>
                    </div>

                    {extractedText && (
                      <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm space-y-4">
                        <div>
                          <label className="block text-xs font-bold text-gray-700 mb-1">Document Identifier (Expert Grouping Name):</label>
                          <input type="text" className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 mb-3" value={documentName} onChange={(e) => setDocumentName(e.target.value)} />
                        </div>
                        <h4 className="font-semibold text-gray-800 text-sm">Parsed Text Layer</h4>
                        <textarea readOnly rows={6} className="w-full border border-gray-200 bg-gray-50 rounded-lg p-3 text-sm font-mono text-gray-700 focus:outline-none" value={extractedText} />
                        <button onClick={handleRunAnalysis} disabled={isAnalyzing} className="w-full sm:w-auto bg-green-600 hover:bg-green-700 disabled:bg-gray-300 text-white px-8 py-3 rounded-lg text-sm font-bold transition shadow">
                          {isAnalyzing ? "Processing Audits..." : "▶ Run Analysis"}
                        </button>
                      </div>
                    )}

                    {isAnalyzing && (
                      <div className="flex items-center space-x-2 text-indigo-700 bg-indigo-50 p-4 border border-indigo-200 rounded-lg animate-pulse">
                        <span className="text-xl">⏳</span>
                        <p className="text-sm font-semibold">
                          {analysisProgress.total > 0 ? `Analyzing requirement ${analysisProgress.current} of ${analysisProgress.total}...` : "Analyzing requirements..."}
                        </p>
                      </div>
                    )}

                    {analysisResults.length > 0 && (
                      <div className="space-y-4">
                        {analysisResults.map((res, index) => {
                          return (
                            <div key={index} className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
                              <div className="bg-gray-50 border-b border-gray-200 px-6 py-3">
                                <span className="font-bold text-sm text-indigo-600">✅ Analyzed sentence #{index + 1}</span>
                              </div>
                              <div className="p-6 grid grid-cols-1 md:grid-cols-2 gap-6">
                                <div className="space-y-4">
                                  <div>
                                    <h5 className="text-xs font-extrabold text-gray-500 uppercase mb-2">Requirement Context:</h5>
                                    <div className="bg-blue-50 text-blue-800 px-4 py-3 rounded-lg border border-blue-100 text-sm">{res.requirement}</div>
                                  </div>
                                  <div>
                                    <h5 className="text-xs font-extrabold text-gray-500 uppercase mb-1">Matched Rule ({res.source_filename}):</h5>
                                    <p className="text-xs text-gray-500 italic">{formatScannableClause(res.clause_text)}</p>
                                  </div>
                                </div>
                                <div className="space-y-4 md:border-l border-gray-100 md:pl-6">
                                  <div>
                                    <h5 className="text-xs font-extrabold text-gray-500 uppercase mb-2">Compliance Evaluation:</h5>
                                    <p className="text-sm text-gray-700 whitespace-pre-line bg-gray-50 p-3 rounded-lg border border-gray-150">{res.analysis}</p>
                                  </div>
                                  <div>
                                    <h5 className="text-xs font-extrabold text-gray-500 uppercase mb-2">Suggested Correction:</h5>
                                    <div className="bg-green-50 text-green-800 px-4 py-3 rounded-lg border border-green-100 text-sm font-medium">{res.suggested_rewrite}</div>
                                  </div>
                                </div>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                )}

                {/* USER TAB: COMPLIANCE LOG HISTORY */}
                {activeTab === "history" && (
                  <div className="space-y-6">
                    <div className="flex justify-between items-center bg-white rounded-xl border border-gray-200 px-6 py-4 shadow-sm">
                      <button onClick={() => setActiveTab("portal")} className="text-indigo-600 hover:text-indigo-800 text-sm font-bold flex items-center space-x-1 focus:outline-none">
                        <span>← Back to Portal</span>
                      </button>
                      <h3 className="text-sm font-bold text-gray-700">History Log</h3>
                    </div>

                    <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
                      <h3 className="text-lg font-bold mb-1">Standard Audit Logs</h3>
                      <p className="text-sm text-gray-500 mb-6">Click on a document to view sentences, and click on a sentence to expand detailed compliance audits.</p>
                      {historyList.length === 0 ? (
                        <div className="text-center py-12 text-gray-400 border border-dashed border-gray-200 rounded-lg">No audit records detected.</div>
                      ) : (
                        <div className="space-y-3">
                          {getGroupedUserHistory().map((doc) => {
                            const isDocExpanded = expandedUserHistDocId === doc.document_id;
                            return (
                              <div key={doc.document_id} className="border border-gray-200 rounded-xl overflow-hidden bg-white shadow-sm animate-fade-in">
                                <div 
                                  onClick={() => setExpandedUserHistDocId(isDocExpanded ? null : doc.document_id)} 
                                  className="px-5 py-4 flex justify-between items-center bg-gray-50/50 cursor-pointer hover:bg-gray-50 transition"
                                >
                                  <div>
                                    <h4 className="font-bold text-sm text-gray-800">📄 {doc.document_name}</h4>
                                    <p className="text-xs text-gray-400 mt-1">Processed: {doc.timestamp}</p>
                                  </div>
                                  <div className="flex items-center space-x-2">
                                    <span className="text-xs bg-indigo-50 text-indigo-700 px-2.5 py-1 rounded-full font-bold">{doc.items.length} sentence(s)</span>
                                    <span className="text-xs text-gray-400">{isDocExpanded ? "▲" : "▼"}</span>
                                  </div>
                                </div>

                                {isDocExpanded && (
                                  <div className="p-4 border-t border-gray-150 bg-white space-y-2">
                                    {doc.items.map((item) => {
                                      const isReqExpanded = expandedUserHistReqId === item.id;
                                      const parsed = parseModelOutput(item.model_output);

                                      return (
                                        <div key={item.id} className="border border-gray-100 rounded-lg overflow-hidden bg-white">
                                          <div 
                                            onClick={() => setExpandedUserHistReqId(isReqExpanded ? null : item.id)} 
                                            className="px-4 py-3 flex justify-between items-center cursor-pointer hover:bg-gray-50/70 transition"
                                          >
                                            <p className={`text-xs font-semibold text-gray-700 ${isReqExpanded ? "whitespace-normal break-words pr-4" : "truncate max-w-4xl"}`}>
                                              🔹 {item.requirement}
                                            </p>    
                                            <span className="text-[10px] text-gray-400">{isReqExpanded ? "▲" : "▼"}</span>
                                          </div>

                                          {isReqExpanded && (
                                            <div className="p-4 bg-gray-50/40 border-t border-gray-100 grid grid-cols-1 md:grid-cols-2 gap-4">
                                              <div className="space-y-2">
                                                <span className="block text-[10px] font-bold text-gray-500 uppercase tracking-wider">Standard Framework Reference:</span>
                                                <p className="text-xs italic text-gray-600 bg-white p-2.5 rounded border border-gray-150 leading-relaxed">{item.matched_rule}</p>
                                              </div>
                                              <div className="space-y-3 border-t md:border-t-0 md:border-l border-gray-150 pt-3 md:pt-0 md:pl-4">
                                                <div>
                                                  <span className="block text-[10px] font-bold text-indigo-700 uppercase tracking-wider mb-1">AI Audit Evaluation:</span>
                                                  <p className="text-xs whitespace-pre-line text-gray-700 bg-white p-2 rounded border border-gray-200">{parsed.analysis}</p>
                                                </div>
                                                <div>
                                                  <span className="block text-[10px] font-bold text-green-700 uppercase tracking-wider mb-1">Suggested Rewrite:</span>
                                                  <p className="text-xs font-bold text-green-900 bg-green-50 p-2.5 rounded border border-green-200 leading-relaxed">{parsed.rewrite}</p>
                                                </div>
                                              </div>
                                            </div>
                                          )}
                                        </div>
                                      );
                                    })}
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {/* COMPARATIVE VIEW */}
                {activeComparison && (
                  <div className="fixed inset-0 bg-gray-950/40 backdrop-blur-sm z-50 flex items-center justify-center p-6 animate-fade-in" onClick={() => setActiveComparison(null)}>
                    <div className="bg-white border border-gray-200 rounded-2xl shadow-2xl p-8 max-w-6xl w-full max-h-[85vh] overflow-y-auto space-y-6 relative" onClick={(e) => e.stopPropagation()}>
                      <button onClick={() => setActiveComparison(null)} className="absolute top-4 right-4 text-gray-400 hover:text-gray-600 text-lg font-black focus:outline-none">✕</button>
                      
                      <div>
                        <h3 className="text-xl font-bold text-gray-950">Expert Comparative Review Matrix</h3>
                        <p className="text-xs text-gray-400 mt-1">Document: {activeComparison.documentName} | Evaluator: {activeComparison.expertUsername}</p>
                      </div>

                      <div className="bg-indigo-50 border border-indigo-100 p-4 rounded-lg text-indigo-900 text-xs font-semibold leading-relaxed">
                        💡 Showing only the specific requirements where the Expert has made custom corrections or suggested rewrites.
                      </div>

                      <div className="space-y-4">
                        {activeComparison.comparisons.map((item, idx) => {
                          return (
                            <div key={item.id} className="border border-gray-100 rounded-xl overflow-hidden shadow-sm">
                              <div className="bg-gray-50 px-4 py-2 border-b border-gray-100 text-xs font-bold text-indigo-700">Sentence set #{idx + 1}</div>
                              <div className="p-4 grid grid-cols-1 md:grid-cols-2 gap-4">
                                <div className="space-y-3">
                                  <div className="bg-indigo-50/50 p-3 rounded-lg">
                                    <span className="block text-[10px] font-bold text-indigo-800 uppercase mb-1">Target Requirement:</span>
                                    <p className="text-xs font-medium">{item.requirement}</p>
                                  </div>
                                  <div className="bg-gray-100 p-3 rounded-lg">
                                    <span className="block text-[10px] font-bold text-gray-600 uppercase mb-1">Standard Reference:</span>
                                    <p className="text-xs italic">{item.matched_rule}</p>
                                  </div>
                                </div>
                                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 border-t md:border-t-0 md:border-l border-gray-100 pt-3 md:pt-0 md:pl-4">
                                  <div className="space-y-3">
                                    <div className="bg-red-50/50 p-3 rounded-lg border border-red-100">
                                      <span className="block text-[10px] font-bold text-red-800 uppercase mb-1">AI RAW EVALUATION (Analysis & Rewrite):</span>
                                      <p className="text-xs whitespace-pre-line">{item.model_output}</p>
                                    </div>
                                  </div>
                                  <div className="space-y-3">
                                    <div className="bg-green-50 p-3 rounded-lg border border-green-200">
                                      <span className="block text-[10px] font-bold text-green-800 uppercase mb-1">EXPERT CORRECTED EVALUATION:</span>
                                      <p className="text-xs font-medium text-green-950">{item.expert_evaluation}</p>
                                      <span className="block text-[10px] font-bold text-green-800 uppercase mt-2 mb-1">EXPERT IMPROVED REWRITE:</span>
                                      <p className="text-xs font-bold text-green-900 bg-white/60 p-2 rounded border border-green-200">{item.expert_rewrite}</p>
                                    </div>
                                  </div>
                                </div>
                              </div>
                            </div>
                          );
                        })}
                        
                        {activeComparison.comparisons.length === 0 && (
                          <div className="text-center py-6 text-xs text-gray-400 border border-dashed border-gray-200 rounded-lg">
                            The expert verified this document set without requiring any manual modifications.
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* ROLE: DOMAIN EXPERT AUDITING WORKSPACE */}
            {user?.role === "Expert" && (
              <div className="space-y-6">
                
                {/* EXPERT DUAL-CARD PORTAL MENU LANDING SCREEN */}
                {activeTab === "portal" && (
                  <div className="space-y-8 animate-fade-in py-4 max-w-5xl mx-auto">
                    <div className="bg-gradient-to-r from-indigo-50 to-blue-50 border border-indigo-100 rounded-2xl p-8 shadow-sm">
                      <h3 className="text-2xl font-black text-indigo-950">Welcome back, Expert {user.full_name}!</h3>
                      <p className="text-sm text-indigo-700/80 mt-2">Access your specialized curation workspaces from the control hub below.</p>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                      {/* Card 1: Review Queue */}
                      <div className="bg-white border border-gray-200 rounded-2xl p-8 hover:border-indigo-200 hover:shadow-md transition group">
                        <span className="text-4xl block mb-4">📥</span>
                        <h4 className="text-lg font-bold text-gray-900 group-hover:text-indigo-600 transition">Expert Verification Queue</h4>
                        <p className="text-xs text-gray-500 leading-relaxed mt-2 mb-6">
                          Claim, lock, and audit pending requirement documents submitted by standard users, establishing human-verified Ground Truths for training.
                        </p>
                        <button onClick={() => { setActiveTab("reviewQueue"); fetchExpertQueueList(); }} className="bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-bold px-6 py-2.5 rounded-xl transition shadow-sm">
                          📥 View Review Queue
                        </button>
                      </div>

                      {/* Card 2: Audited History */}
                      <div className="bg-white border border-gray-200 rounded-2xl p-8 hover:border-indigo-200 hover:shadow-md transition group">
                        <span className="text-4xl block mb-4">📜</span>
                        <h4 className="text-lg font-bold text-gray-900 group-hover:text-indigo-600 transition">My Audited History Log</h4>
                        <p className="text-xs text-gray-500 leading-relaxed mt-2 mb-6">
                          Inspect your completed historical verifications, review curated requirement edits, and track logs successfully staging for model retraining.
                        </p>
                        <button onClick={() => { setActiveTab("expertHistory"); fetchExpertHistoryList(); }} className="bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-bold px-6 py-2.5 rounded-xl transition shadow-sm">
                          📜 View Audited Logs
                        </button>
                      </div>
                    </div>
                  </div>
                )}

                {/* EXPERT TAB: PENDING EVALUATIONS QUEUE */}
                {activeTab === "reviewQueue" && (
                  <div className="space-y-6">
                    <div className="flex justify-between items-center bg-white rounded-xl border border-gray-200 px-6 py-4 shadow-sm">
                      <button onClick={() => setActiveTab("portal")} className="text-indigo-600 hover:text-indigo-800 text-sm font-bold flex items-center space-x-1 focus:outline-none">
                        <span>← Back to Portal</span>
                      </button>
                      <h3 className="text-sm font-bold text-gray-700">Verification Queue</h3>
                    </div>

                    <div className="space-y-4">
                      <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
                        <h3 className="text-lg font-bold">Expert Verification Queue</h3>
                        <p className="text-sm text-gray-500">Exclusively claim, review, and curate requirements to configure the staging dataset flywheel.</p>
                      </div>

                      <div className="space-y-3">
                        {expertQueue.map((doc) => {
                          const isExpanded = expandedDocId === doc.document_id;
                          const isClaimedByMe = doc.assigned_expert === user.username && doc.lifecycle_status === "LOCKED";
                          const activeDocument = expertQueue.find(
                            item => item.lifecycle_status === "LOCKED" && item.assigned_expert === user.username
                          );
                          const hasOtherActiveDocument = activeDocument && activeDocument.document_id !== doc.document_id;

                          return (
                            <div key={doc.document_id} className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden animate-fade-in">
                              <div className="px-6 py-4 flex flex-col sm:flex-row justify-between items-start sm:items-center space-y-3 sm:space-y-0 hover:bg-gray-50/50 transition">
                                <div onClick={() => isClaimedByMe && handleExpandDocument(doc.document_id)} className="flex-grow cursor-pointer">
                                  <h4 className="font-bold text-gray-900 text-sm flex items-center space-x-2">
                                    <span>📄 {doc.document_name}</span>
                                    <span className={`text-[10px] px-2 py-0.5 rounded-full font-bold ${doc.lifecycle_status === "LOCKED" ? "bg-yellow-100 text-yellow-800" : "bg-green-100 text-green-800"}`}>
                                      {doc.lifecycle_status === "LOCKED" ? "Your active review" : "Available"}
                                    </span>
                                  </h4>
                                  <p className="text-xs text-gray-500 mt-1">Submitter: {doc.submitter} | Last Modified: {doc.timestamp}</p>
                                </div>
                                <div className="flex space-x-2 shrink-0">
                                  {!isClaimedByMe && (
                                    <button
                                      onClick={() => handleClaimDocument(doc.document_id)}
                                      disabled={hasOtherActiveDocument}
                                      title={hasOtherActiveDocument ? `Finish or release ${activeDocument.document_name} first` : "Claim this document"}
                                      className="bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-300 disabled:cursor-not-allowed text-white text-xs font-bold px-4 py-2 rounded-lg transition"
                                    >
                                      {hasOtherActiveDocument ? "Complete Active Review First" : "Lock & Audit"}
                                    </button>
                                  )}
                                  {isClaimedByMe && (
                                    <div className="flex space-x-2 shrink-0">
                                      <button onClick={() => handleUnlockDocument(doc.document_id)} className="bg-red-50 hover:bg-red-100 text-red-700 text-xs font-bold px-4 py-2 rounded-lg transition">
                                        🔓 Release Lock
                                      </button>
                                      <button onClick={() => handleExpandDocument(doc.document_id)} className="bg-gray-150 hover:bg-gray-200 text-gray-700 text-xs font-bold px-4 py-2 rounded-lg transition">
                                        {isExpanded ? "Collapse View" : "✏️ Edit Requirements"}
                                      </button>
                                    </div>
                                  )}
                                </div>
                              </div>

                              {/* COLLAPSIBLE ACCORDION CONTAINER */}
                              {isExpanded && isClaimedByMe && (
                                <div className="px-6 pb-6 pt-3 border-t border-gray-100 space-y-6">
                                  <div className="space-y-4">
                                    {expertActiveReqs.map((req, idx) => {
                                      return (
                                        <div key={req.id} className="border border-gray-100 rounded-xl overflow-hidden shadow-sm">
                                          <div className="bg-gray-50 px-4 py-2.5 border-b border-gray-100 text-xs font-bold text-indigo-700">Sentence set #{idx + 1}</div>
                                          <div className="p-4 grid grid-cols-1 md:grid-cols-2 gap-6">
                                            {/* Left Column: Requirement Context & Reference Standards */}
                                            <div className="space-y-3">
                                              <div className="bg-indigo-50/50 p-3 rounded-lg">
                                                <span className="block text-[10px] font-extrabold text-indigo-800 uppercase mb-1">Requirement:</span>
                                                <p className="text-xs font-semibold">{req.requirement}</p>
                                              </div>
                                              <div className="bg-gray-100 p-3 rounded-lg">
                                                <span className="block text-[10px] font-extrabold text-gray-600 uppercase mb-1">Standard reference:</span>
                                                <p className="text-xs italic text-gray-700">{req.matched_rule}</p>
                                              </div>
                                            </div>
                                            
                                            {/* Right Column (Direct Edit Column): Analysis & Rewrite textareas pre-filled with raw AI outputs */}
                                            <div className="space-y-3 md:border-l border-gray-150 md:pl-6">
                                              <div>
                                                <label className="block text-[10px] font-extrabold text-indigo-700 uppercase mb-1">🔍 Edit AI Analysis Evaluation:</label>
                                                <textarea rows={4} className="w-full border border-gray-300 rounded-lg p-3 text-xs font-medium focus:ring-1 focus:ring-indigo-500 font-sans" value={expertEdits[req.id]?.expert_evaluation || ""} onChange={(e) => handleUpdateEditField(req.id, "expert_evaluation", e.target.value)} />
                                              </div>
                                              <div>
                                                <label className="block text-[10px] font-extrabold text-green-700 uppercase mb-1 font-bold">✏️ Edit AI Suggested Rewrite:</label>
                                                <textarea rows={3} className="w-full border border-gray-300 rounded-lg p-3 text-xs font-bold focus:ring-1 focus:ring-green-500 font-sans" value={expertEdits[req.id]?.expert_rewrite || ""} onChange={(e) => handleUpdateEditField(req.id, "expert_rewrite", e.target.value)} />
                                              </div>
                                            </div>
                                          </div>
                                        </div>
                                      );
                                    })}
                                  </div>

                                  <div className="flex space-x-3 justify-end pt-3 border-t border-gray-100">
                                    <button onClick={() => handleSubmitExpertAudit(doc.document_id, false)} className="px-5 py-2.5 bg-red-100 hover:bg-red-200 text-red-700 text-xs font-bold rounded-lg transition">
                                      Reject Document
                                    </button>
                                    <button onClick={() => handleSubmitExpertAudit(doc.document_id, true)} className="px-6 py-2.5 bg-green-600 hover:bg-green-700 text-white text-xs font-bold rounded-lg transition shadow-sm">
                                      ✅ Approve & Export to Flywheel
                                    </button>
                                  </div>
                                </div>
                              )}
                            </div>
                          );
                        })}

                        {expertQueue.length === 0 && (
                          <div className="text-center py-12 text-gray-400 bg-white border border-gray-200 rounded-lg animate-pulse">Review Queue is completely clean!</div>
                        )}
                      </div>
                    </div>
                  </div>
                )}

                {/* EXPERT TAB: EXPERT HISTORICAL ARCHIVE */}
                {activeTab === "expertHistory" && (
                  <div className="space-y-6">
                    <div className="flex justify-between items-center bg-white rounded-xl border border-gray-200 px-6 py-4 shadow-sm">
                      <button onClick={() => setActiveTab("portal")} className="text-indigo-600 hover:text-indigo-800 text-sm font-bold flex items-center space-x-1 focus:outline-none">
                        <span>← Back to Portal</span>
                      </button>
                      <h3 className="text-sm font-bold text-gray-700">My Audited History</h3>
                    </div>

                    <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
                      <h3 className="text-lg font-bold mb-1">My Audited Logs</h3>
                      <p className="text-sm text-gray-500 mb-6">Historical archive of requirements approved and pushed to the fine-tuning pool. Click on any document to see the curated review details you submitted.</p>
                      
                      {expertHistory.length === 0 ? (
                        <div className="text-center py-12 text-gray-400 border border-dashed border-gray-200 rounded-lg">No audit logs established.</div>
                      ) : (
                        <div className="space-y-3">
                          {expertHistory.map((item) => {
                            const isHistDocExpanded = expandedExpertHistDocId === item.document_id;
                            return (
                              <div key={item.document_id} className="border border-gray-200 rounded-xl overflow-hidden bg-white shadow-sm">
                                {/* Audited Log Row Trigger */}
                                <div 
                                  onClick={() => handleExpandExpertHistory(item.document_id)} 
                                  className="px-5 py-4 flex justify-between items-center bg-gray-50/50 cursor-pointer hover:bg-gray-50 transition"
                                >
                                  <div>
                                    <h4 className="font-bold text-sm text-gray-800">📄 {item.document_name}</h4>
                                    <p className="text-xs text-gray-400 mt-1">Auditor: {user.username} | Submitter: {item.submitter}</p>
                                  </div>
                                  <span className="text-xs text-gray-400">{isHistDocExpanded ? "▲" : "▼"}</span>
                                </div>

                                {/* Audited Log Requirements List Container */}
                                {isHistDocExpanded && (
                                  <div className="px-6 pb-6 pt-3 border-t border-gray-100 bg-white space-y-4">
                                    {expertHistoryReqs.map((req, idx) => {
                                      return (
                                        <div key={req.id} className="border border-gray-100 rounded-xl overflow-hidden shadow-sm animate-fade-in">
                                          <div className="bg-gray-50 px-4 py-2 border-b border-gray-100 text-xs font-bold text-indigo-700">Audit sentence #{idx + 1}</div>
                                          <div className="p-4 grid grid-cols-1 md:grid-cols-2 gap-4">
                                            <div className="space-y-3">
                                              <div className="bg-indigo-50/50 p-3 rounded-lg">
                                                <span className="block text-[10px] font-bold text-indigo-800 uppercase mb-1">Requirement:</span>
                                                <p className="text-xs">{req.requirement}</p>
                                              </div>
                                              <div className="bg-gray-100 p-3 rounded-lg">
                                                <span className="block text-[10px] font-bold text-gray-600 uppercase mb-1">Standard reference:</span>
                                                <p className="text-xs italic">{req.matched_rule}</p>
                                              </div>
                                            </div>
                                            <div className="space-y-3 border-t md:border-t-0 md:border-l border-gray-100 pt-3 md:pt-0 md:pl-4">
                                              <div className="bg-green-50 p-3 rounded-lg border border-green-200">
                                                <span className="block text-[10px] font-bold text-green-800 uppercase mb-1 font-extrabold">Your Curated Evaluation:</span>
                                                <p className="text-xs text-green-950 whitespace-pre-line leading-relaxed">{req.expert_evaluation}</p>
                                                <span className="block text-[10px] font-bold text-green-800 uppercase mt-2 mb-1 font-extrabold">Your Curated Rewrite:</span>
                                                <p className="text-xs font-bold text-green-900 bg-white/60 p-2 rounded border border-green-200">{req.expert_rewrite}</p>
                                              </div>
                                            </div>
                                          </div>
                                        </div>
                                      );
                                    })}
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* ROLE: COMPREHENSIVE ADMINISTRATIVE SPLIT WORKSPACE */}
            {user?.role === "Admin" && (
              <div className="space-y-6">
                <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
                  <h3 className="text-lg font-bold">Admin Curation Console</h3>
                  <p className="text-sm text-gray-500">Monitor raw user interactions alongside expert-approved structural audits.</p>
                </div>
                
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                  {[
                    { key: "pending", label: "Pending", headerClass: "text-blue-800 bg-blue-50 border-blue-100" },
                    { key: "locked", label: "Locked", headerClass: "text-yellow-800 bg-yellow-50 border-yellow-100" },
                    { key: "approved", label: "Approved", headerClass: "text-green-800 bg-green-50 border-green-100" },
                    { key: "rejected", label: "Rejected", headerClass: "text-red-800 bg-red-50 border-red-100" }
                  ].map((section) => (
                    <div key={section.key} className="space-y-4">
                      <h4 className={`font-bold text-sm px-4 py-2.5 rounded-lg border ${section.headerClass}`}>
                        {section.label} Records ({adminLogsData[section.key]?.length || 0})
                      </h4>
                      <div className="space-y-4 max-h-[600px] overflow-y-auto pr-2">
                        {adminLogsData[section.key]?.map((log) => (
                          <div key={log.id} className="bg-white border border-gray-200 rounded-xl p-4 space-y-3 shadow-sm animate-fade-in">
                            <div className="text-[10px] font-bold text-gray-400">
                              ID #{log.id} | User: {log.username} | Expert: {log.assigned_expert || "—"} | Export: {log.export_status}
                            </div>
                            <div className="text-[10px] text-gray-400">Document: {log.document_name} | {log.timestamp}</div>
                            <div>
                              <span className="text-[10px] font-extrabold text-gray-500 uppercase block">Requirement</span>
                              <p className="text-xs font-semibold text-gray-800">{log.requirement}</p>
                            </div>
                            <div>
                              <span className="text-[10px] font-extrabold text-gray-500 uppercase block">Matched Standard Rule</span>
                              <p className="text-xs italic text-gray-600 line-clamp-3">{log.matched_rule}</p>
                            </div>
                            {section.key === "approved" && (
                              <div className="bg-green-50 p-2.5 rounded border border-green-100">
                                <p className="text-[11px] text-green-950">{log.expert_evaluation}</p>
                                <p className="text-[11px] font-bold text-green-900 mt-2">{log.expert_rewrite}</p>
                              </div>
                            )}
                            <div className="flex flex-wrap gap-2 pt-2">
                              <button onClick={() => handleAdminDelete(log)} className="bg-red-50 hover:bg-red-100 text-red-700 text-[10px] font-bold px-3 py-1.5 rounded-lg transition">
                                Delete Requirement
                              </button>
                              <button onClick={() => handleAdminDeleteDocument(log)} className="bg-red-600 hover:bg-red-700 text-white text-[10px] font-bold px-3 py-1.5 rounded-lg transition">
                                Delete Document
                              </button>
                            </div>
                          </div>
                        ))}
                        {adminLogsData[section.key]?.length === 0 && (
                          <p className="text-center text-xs text-gray-400 py-10 border border-dashed border-gray-200 rounded-lg bg-white">No {section.label.toLowerCase()} records.</p>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

          </div>
        )}

      </main>
    </div>
  );
}

// Scannable formatter helper
function formatScannableClause(raw, limit = 150) {
  let clean = raw.trim().replace(/^[a-z\s,.)-]+/, '');
  if (clean && clean[0] === clean[0].toLowerCase()) {
    clean = clean[0].toUpperCase() + clean.slice(1);
  }
  return clean.length > limit ? clean.slice(0, limit) + "..." : clean;
}
