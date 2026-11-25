import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Activity, Bot, ChevronLeft, ChevronRight, Command, Cpu, Gauge, History, Menu, MessageSquarePlus, PanelLeftClose, Search, Send, Settings2, Sparkles, Trash2, WandSparkles, X, Zap } from 'lucide-react';
import './style.css';

const API = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, '');
const STORAGE_KEY = 'lyftr-ai-session-index-v1';
const newId = () => 's-' + crypto.randomUUID();
const safeText = value => typeof value === 'string' ? value : String(value ?? '');
const starters = [
  { icon: <WandSparkles size={18}/>, title: 'Create something', prompt: 'Help me brainstorm a creative product idea and turn it into a simple launch plan.' },
  { icon: <Cpu size={18}/>, title: 'Explain a concept', prompt: 'Explain how large language models work in simple terms, with an analogy.' },
  { icon: <Zap size={18}/>, title: 'Solve a problem', prompt: 'Help me break down a difficult problem into clear, actionable steps.' },
  { icon: <Activity size={18}/>, title: 'Analyze & improve', prompt: 'Give me a framework for analyzing an idea and improving its weak points.' },
];
function readSessions() {
  try {
    const data = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
    return Array.isArray(data) ? data.filter(x => x && typeof x.id === 'string' && typeof x.title === 'string').slice(0, 100) : [];
  } catch { return []; }
}
function App() {
  const [sessionId, setSessionId] = useState(newId);
  const [sessions, setSessions] = useState(readSessions);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [showSettings, setShowSettings] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [health, setHealth] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [search, setSearch] = useState('');
  const endRef = useRef(null);
  const conversationRef = useRef(null);
  const requestRef = useRef(0);

  useEffect(() => {
    let active = true;
    fetch(`${API}/health`).then(r => { if (!r.ok) throw new Error('Health check failed'); return r.json(); })
      .then(data => { if (active) setHealth(data); }).catch(() => { if (active) setHealth(null); });
    return () => { active = false; };
  }, []);
  useEffect(() => { try { localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions)); } catch {} }, [sessions]);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }); }, [messages, busy]);

  const visibleSessions = useMemo(() => sessions.filter(s => s.title.toLowerCase().includes(search.toLowerCase())), [sessions, search]);
  const currentTitle = sessions.find(s => s.id === sessionId)?.title || 'New conversation';

  function remember(id, firstMessage) {
    const title = firstMessage.replace(/\s+/g, ' ').trim().slice(0, 60) || 'New conversation';
    setSessions(prev => [{ id, title, updated: Date.now() }, ...prev.filter(s => s.id !== id)].slice(0, 100));
  }
  async function send(e, override) {
    e?.preventDefault();
    const message = (override ?? input).trim();
    if (!message || busy || loadingHistory) return;
    if (message.length > 4000) { setMessages(m => [...m, { role: 'error', content: 'Message must be at most 4000 characters.' }]); return; }
    const currentId = sessionId;
    const requestNumber = ++requestRef.current;
    const isFirstMessage = !messages.some(m => m.role === 'user');
    setInput(''); setBusy(true);
    setMessages(m => [...m, { role: 'user', content: message }]);
    try {
      const response = await fetch(`${API}/chat`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session_id: currentId, message, ...(systemPrompt ? { system_prompt: systemPrompt } : {}) }) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Request failed. Please try again.');
      if (requestNumber !== requestRef.current) return;
      setMessages(m => [...m, { role: 'assistant', content: data.reply, metadata: data.metadata }]);
      remember(currentId, isFirstMessage ? message : (sessions.find(s => s.id === currentId)?.title || message));
    } catch (err) {
      if (requestNumber === requestRef.current) setMessages(m => [...m, { role: 'error', content: err.message || 'Unable to reach the server.' }]);
    } finally { if (requestNumber === requestRef.current) setBusy(false); }
  }
  function reset() {
    if (busy || loadingHistory) return;
    ++requestRef.current; setSessionId(newId()); setMessages([]); setInput(''); setSystemPrompt(''); setMobileOpen(false);
    if (conversationRef.current) conversationRef.current.scrollTop = 0;
  }
  async function openSession(id) {
    if (busy || loadingHistory || id === sessionId) return;
    const requestNumber = ++requestRef.current; setLoadingHistory(true); setMobileOpen(false);
    try {
      const response = await fetch(`${API}/sessions/${encodeURIComponent(id)}/messages`); const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Could not load conversation.');
      if (requestNumber !== requestRef.current) return;
      setSessionId(id); setMessages(Array.isArray(data.messages) ? data.messages : []); setInput(''); setSystemPrompt('');
      if (conversationRef.current) conversationRef.current.scrollTop = 0;
    } catch (err) { if (requestNumber === requestRef.current) setMessages(m => [...m, { role: 'error', content: `History load failed: ${err.message}` }]); }
    finally { if (requestNumber === requestRef.current) setLoadingHistory(false); }
  }
  function forgetLocalSession(id, e) { e.stopPropagation(); if (busy || loadingHistory) return; setSessions(prev => prev.filter(s => s.id !== id)); if (id === sessionId) reset(); }

  return <div className="shell">
    <div className="ambient ambient-one"/><div className="ambient ambient-two"/><div className="noise"/>
    <aside className={`sidebar ${sidebarOpen ? '' : 'collapsed'} ${mobileOpen ? 'mobile-open' : ''}`}>
      <div className="side-head">
        <div className="logo-mark"><Sparkles size={20}/></div>
        <div className="brand-copy"><b>NOVA</b><span>AI workspace</span></div>
        <button className="icon-btn side-collapse" onClick={() => setSidebarOpen(v => !v)}>{sidebarOpen ? <PanelLeftClose size={18}/> : <ChevronRight size={18}/>}</button>
        <button className="icon-btn mobile-close" onClick={() => setMobileOpen(false)}><X size={18}/></button>
      </div>
      <button className="new-chat" onClick={reset} disabled={busy || loadingHistory}><MessageSquarePlus size={18}/><span>New conversation</span><kbd>⌘ K</kbd></button>
      <div className="search-wrap"><Search size={15}/><input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search chats..."/></div>
      <div className="section-label"><span>RECENT</span><span>{sessions.length}</span></div>
      <nav className="history-list">
        {visibleSessions.length === 0 && <div className="empty-history"><History size={20}/><span>No conversations yet</span></div>}
        {visibleSessions.map(s => <div className={`history-entry ${s.id === sessionId ? 'active' : ''}`} key={s.id}>
          <button className="history-open" onClick={() => openSession(s.id)} disabled={busy || loadingHistory}><span className="history-glyph"><Command size={14}/></span><span>{s.title}</span></button>
          <button className="history-remove" onClick={e => forgetLocalSession(s.id, e)} aria-label="Remove chat"><Trash2 size={14}/></button>
        </div>)}
      </nav>
      <div className="system-card">
        <div className="system-row"><span className={`pulse ${health ? 'online' : ''}`}/><div><b>{health ? 'Systems online' : 'Backend offline'}</b><span>{health ? 'Ready for inference' : 'Check API connection'}</span></div></div>
        {health && <div className="system-stats"><span><Gauge size={13}/>{health.keys_configured} keys</span><span><Zap size={13}/>Cache on</span></div>}
      </div>
    </aside>
    <main className="main">
      <header className="topbar">
        <div className="top-left"><button className="icon-btn mobile-menu" onClick={() => setMobileOpen(true)}><Menu size={19}/></button><div><div className="eyebrow">NOVA / CHAT</div><h2>{currentTitle}</h2></div></div>
        <div className="top-actions"><div className={`connection-pill ${health ? 'connected' : ''}`}><span/>{health ? 'Connected' : 'Offline'}</div><button className={`icon-btn ${showSettings ? 'selected' : ''}`} onClick={() => setShowSettings(v => !v)} title="Assistant settings"><Settings2 size={18}/></button></div>
      </header>
      {showSettings && <div className="settings-panel"><div><b>Assistant instructions</b><span>Shape the behavior for this conversation.</span></div><textarea value={systemPrompt} onChange={e => setSystemPrompt(e.target.value)} placeholder="e.g. Be concise, technical, and include examples..." rows="2"/></div>}
      <section className="conversation" ref={conversationRef}>
        {loadingHistory && <div className="center-state"><div className="orb small"><Sparkles/></div><span>Restoring conversation...</span></div>}
        {!loadingHistory && messages.length === 0 && <div className="hero">
          <div className="hero-visual"><div className="orbit orbit-a"/><div className="orbit orbit-b"/><div className="orb"><Sparkles size={31}/></div><span className="particle p1"/><span className="particle p2"/><span className="particle p3"/></div>
          <div className="hero-kicker"><span/> INTELLIGENCE, AMPLIFIED <span/></div>
          <h1>What will we <em>create</em> today?</h1>
          <p>Think, build, explore, and solve with an AI workspace designed to keep your ideas moving.</p>
          <div className="starter-grid">{starters.map(card => <button key={card.title} onClick={() => { setInput(card.prompt); }}><span className="starter-icon">{card.icon}</span><span><b>{card.title}</b><small>{card.prompt}</small></span><ChevronRight size={16}/></button>)}</div>
        </div>}
        <div className="thread">{messages.map((m, i) => <div className={`message ${m.role}`} key={i}>
          <div className="avatar">{m.role === 'assistant' ? <Bot size={18}/> : m.role === 'user' ? 'Y' : '!'}</div>
          <div className="message-body"><div className="message-label">{m.role === 'assistant' ? 'NOVA' : m.role === 'user' ? 'YOU' : 'SYSTEM'}</div><div className="bubble">{m.role === 'assistant' ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{safeText(m.content)}</ReactMarkdown> : safeText(m.content)}</div>
          {m.metadata && <div className="metadata"><span className={m.metadata.resolution_source === 'LLM_CACHE' ? 'cache' : 'live'}>{m.metadata.resolution_source === 'LLM_CACHE' ? 'CACHE HIT' : 'LIVE'}</span><span>{m.metadata.latency_ms} ms</span><span>{m.metadata.input_tokens} in / {m.metadata.output_tokens} out</span><span>{safeText(m.metadata.model).replace('nvidia/','')}</span></div>}</div>
        </div>)}
        {busy && <div className="message assistant thinking"><div className="avatar"><Bot size={18}/></div><div className="message-body"><div className="message-label">NOVA</div><div className="typing"><i/><i/><i/><span>Thinking</span></div></div></div>}<div ref={endRef}/></div>
      </section>
      <div className="composer-zone"><form className="composer" onSubmit={send}><div className="composer-glow"/><textarea value={input} onChange={e => setInput(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }} placeholder="Ask anything. Build anything." rows="1" maxLength="4000" disabled={busy || loadingHistory}/><div className="composer-foot"><div><Sparkles size={14}/><span>NOVA can make mistakes. Verify important information.</span></div><button type="submit" disabled={busy || loadingHistory || !input.trim()}><Send size={17}/></button></div></form><div className="shortcut"><kbd>Enter</kbd> send <span>·</span> <kbd>Shift + Enter</kbd> new line</div></div>
    </main>
    {mobileOpen && <button className="scrim" onClick={() => setMobileOpen(false)} aria-label="Close menu"/>}
  </div>;
}
createRoot(document.getElementById('root')).render(<App/>);
