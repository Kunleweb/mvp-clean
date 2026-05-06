"use client";

import React, { useState, useEffect, useRef } from 'react';
import { BarChart, Bar, LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell } from 'recharts';
import { UploadCloud, Database, Activity, CheckCircle, AlertTriangle, FileText, Check, AlertCircle, X, Download, Loader2 } from 'lucide-react';

const API_URL = 'http://localhost:8001';

type KPI = { total_assets: number; avg_quality_score: number; rank_a_count: number; below_gate_count: number };
type Asset = { asset_id: number; asset_name: string; format: string; source_name: string; source_type: string; score: number; rank: string; total_rows: number; duplicate_rows: number; evaluated_at: string };
type Audit = { revision_id: number; edited_by: string; edit_note: string | null; file_path: string | null; edited_at: string };

export default function ModernDashboard() {
  const [kpis, setKpis] = useState<KPI | null>(null);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [audits, setAudits] = useState<Audit[]>([]);
  
  const [file, setFile] = useState<File | null>(null);
  const [uploadStatus, setUploadStatus] = useState<string>('');
  const [uploadState, setUploadState] = useState<'idle' | 'uploading' | 'success' | 'error'>('idle');
  const [jobId, setJobId] = useState<string | null>(null);
  
  // Drilldown Modal State
  const [selectedAsset, setSelectedAsset] = useState<Asset | null>(null);
  const [drilldownData, setDrilldownData] = useState<any>(null);
  const [historyData, setHistoryData] = useState<any[]>([]);
  const [isLoadingDrilldown, setIsLoadingDrilldown] = useState(false);
  
  // Data Explorer State
  const [drilldownTab, setDrilldownTab] = useState<'quality' | 'explorer'>('quality');
  const [explorerViewMode, setExplorerViewMode] = useState<'grid' | 'raw'>('raw');
  const [explorerData, setExplorerData] = useState<{columns: string[], rows: any[]}>({columns: [], rows: []});
  const [hasEdits, setHasEdits] = useState(false);
  const [rawJsonText, setRawJsonText] = useState("");
  const [jsonError, setJsonError] = useState("");
  const [showGovModal, setShowGovModal] = useState(false);
  const [govName, setGovName] = useState('');
  const [govReason, setGovReason] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);

  // Ingestion UI State
  const [ingestMode, setIngestMode] = useState<'local' | 'api'>('local');
  const [apiSource, setApiSource] = useState<'alpha-vantage' | null>('alpha-vantage');
  const [apiSymbol, setApiSymbol] = useState<string>('AAPL');

  const dropZoneRef = useRef<HTMLDivElement>(null);

  const fetchData = async () => {
    try {
      const noStore = { cache: 'no-store' as RequestCache };
      const [k, a, au] = await Promise.all([
        fetch(`${API_URL}/api/kpis`, noStore).then(r => r.json()),
        fetch(`${API_URL}/api/assets/quality`, noStore).then(r => r.json()),
        fetch(`${API_URL}/api/audit-logs?limit=5`, noStore).then(r => r.json())
      ]);
      setKpis(k); setAssets(a); setAudits(au);
    } catch (err) {
      console.error("Failed to load data", err);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (!jobId) return;
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`${API_URL}/status/${jobId}`);
        const data = await res.json();
        setUploadStatus(`Processing: ${data.status || 'Working...'}`);
        if (data.state === 'SUCCESS' || data.state === 'FAILURE') {
          clearInterval(interval);
          setUploadState(data.state === 'SUCCESS' ? 'success' : 'error');
          if (data.state === 'SUCCESS') fetchData();
        }
      } catch (err) {
        setUploadState('error');
      }
    }, 2000);
    return () => clearInterval(interval);
  }, [jobId]);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) processFile(e.target.files[0]);
  };

  const processFile = (selectedFile: File) => {
    if (selectedFile.size > 1024 * 1024) {
      setUploadState('error');
      setUploadStatus("File too large. Limit is 1MB.");
      setFile(null);
      return;
    }
    setFile(selectedFile);
    setUploadState('idle');
    setUploadStatus("Ready to upload");
    setJobId(null);
  };

  const uploadSelectedFile = async () => {
    if (!file) return;
    setUploadState('uploading');
    setUploadStatus("Uploading to server...");
    
    const formData = new FormData();
    formData.append("file", file);
    
    try {
      const res = await fetch(`${API_URL}/upload`, { method: 'POST', body: formData });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail);
      setJobId(data.job_id);
      setUploadStatus("Queued for processing...");
      setFile(null);
    } catch (err: any) {
      setUploadState('error');
      setUploadStatus(`Error: ${err.message}`);
    }
  };

  const triggerApiIngestion = async () => {
    if (!apiSymbol.trim() || !apiSource) return;
    setUploadState('uploading');
    setUploadStatus(`Fetching ${apiSymbol} from ${apiSource}...`);
    
    try {
      const res = await fetch(`${API_URL}/ingest/api/${apiSource}?symbol=${apiSymbol.trim()}`, { method: 'POST' });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail);
      setJobId(data.job_id);
      setUploadStatus("API fetched & queued for processing...");
    } catch (err: any) {
      setUploadState('error');
      setUploadStatus(`API Error: ${err.message}`);
    }
  };

  const openDrilldown = async (asset: Asset) => {
    setSelectedAsset(asset);
    setIsLoadingDrilldown(true);
    setDrilldownTab('quality');
    setDrilldownData(null);
    setHistoryData([]);
    setExplorerData({columns: [], rows: []});
    setRawJsonText('');
    setJsonError('');
    setHasEdits(false);
    
    try {
      const [ddRes, histRes, dataRes] = await Promise.all([
        fetch(`${API_URL}/api/assets/${asset.asset_id}/quality/drilldown`),
        fetch(`${API_URL}/api/assets/${asset.asset_id}/history`),
        fetch(`${API_URL}/api/assets/${asset.asset_id}/data?limit=50`)
      ]);
      if (ddRes.ok) setDrilldownData(await ddRes.json());
      if (histRes.ok) {
        const hData = await histRes.json();
        // Format dates for the chart
        setHistoryData(hData.map((h: any) => ({
          ...h,
          formatted_date: new Date(h.evaluated_at).toLocaleDateString([], { month: 'short', day: 'numeric' })
        })).reverse());
      }
      if (dataRes.ok) {
         const data = await dataRes.json();
         setExplorerData(data);
         setRawJsonText(data.raw_text || '');
         const isRawDefault = asset.asset_name.toLowerCase().endsWith('.json') || asset.asset_name.toLowerCase().endsWith('.md');
         setExplorerViewMode(isRawDefault ? 'raw' : 'grid');
      }
    } catch (e) {
      console.error("Failed to load drilldown or data", e);
    } finally {
      setIsLoadingDrilldown(false);
    }
  };

  const onDragOver = (e: React.DragEvent) => { e.preventDefault(); dropZoneRef.current?.classList.add('dragover'); };
  const onDragLeave = (e: React.DragEvent) => { e.preventDefault(); dropZoneRef.current?.classList.remove('dragover'); };
  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    dropZoneRef.current?.classList.remove('dragover');
    if (e.dataTransfer.files.length) processFile(e.dataTransfer.files[0]);
  };

  return (
    <div className="container" style={{ position: 'relative' }}>
      
      {/* Modal Overlay */}
      {selectedAsset && (
        <div style={{
          position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
          backgroundColor: 'rgba(15, 23, 42, 0.6)', backdropFilter: 'blur(4px)',
          zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '2rem'
        }}>
          <div className="card" style={{ width: '100%', maxWidth: '800px', maxHeight: '90vh', overflowY: 'auto', position: 'relative' }}>
            <button 
              onClick={() => setSelectedAsset(null)}
              style={{ position: 'absolute', top: '1rem', right: '1rem', background: 'none', border: 'none', cursor: 'pointer', color: 'var(--muted-foreground)' }}
            >
              <X size={24} />
            </button>
            <div className="flex items-center gap-4 mb-6">
              <Database size={32} color="var(--primary)" />
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <h2 style={{ margin: 0, fontSize: '1.5rem', marginBottom: '0.25rem' }}>{selectedAsset.asset_name}</h2>
                  <button 
                    onClick={() => setShowDeleteModal(true)}
                    style={{ backgroundColor: '#fee2e2', color: '#dc2626', border: '1px solid #fecaca', padding: '0.4rem 0.8rem', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.85rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.4rem' }}
                  >
                    <X size={16} /> Delete Asset
                  </button>
                </div>
                <div style={{ display: 'flex', gap: '1.5rem', borderBottom: '1px solid var(--border)' }}>
                  <button onClick={() => setDrilldownTab('quality')} style={{ fontSize: '1rem', background: 'none', border: 'none', padding: '0.5rem 0', cursor: 'pointer', fontWeight: drilldownTab === 'quality' ? 600 : 400, color: drilldownTab === 'quality' ? 'var(--primary)' : 'var(--muted-foreground)', borderBottom: drilldownTab === 'quality' ? '2px solid var(--primary)' : '2px solid transparent' }}>Quality Overview</button>
                  <button onClick={() => setDrilldownTab('explorer')} style={{ fontSize: '1rem', background: 'none', border: 'none', padding: '0.5rem 0', cursor: 'pointer', fontWeight: drilldownTab === 'explorer' ? 600 : 400, color: drilldownTab === 'explorer' ? 'var(--primary)' : 'var(--muted-foreground)', borderBottom: drilldownTab === 'explorer' ? '2px solid var(--primary)' : '2px solid transparent' }}>Data Explorer (Preview)</button>
                </div>
              </div>
            </div>

            {isLoadingDrilldown ? (
              <p style={{ textAlign: 'center', padding: '3rem' }}>Fetching data and granular metrics...</p>
            ) : drilldownTab === 'quality' ? (
              <div className="flex-col gap-4">
                {/* Metrics Row */}
                <div className="grid grid-cols-4 mb-6">
                  <div style={{ padding: '1rem', backgroundColor: 'var(--muted)', borderRadius: 'var(--radius)' }}>
                    <h3>Current Score</h3>
                    <p style={{ fontSize: '1.5rem', fontWeight: 600, color: 'var(--foreground)' }}>{drilldownData?.score?.toFixed(1) || '-'}%</p>
                  </div>
                  <div style={{ padding: '1rem', backgroundColor: 'var(--muted)', borderRadius: 'var(--radius)' }}>
                    <h3>Status Rank</h3>
                    <span className={`badge ${drilldownData?.rank === 'A' ? 'badge-success' : drilldownData?.rank === 'B' ? 'badge-info' : drilldownData?.rank === 'C' ? 'badge-warning' : 'badge-danger'}`} style={{ marginTop: '0.5rem', fontSize: '1rem' }}>
                      {drilldownData?.rank || '-'}
                    </span>
                  </div>
                  <div style={{ padding: '1rem', backgroundColor: 'var(--muted)', borderRadius: 'var(--radius)' }}>
                    <h3>Duplicate Rows</h3>
                    <p style={{ fontSize: '1.5rem', fontWeight: 600, color: drilldownData?.duplicate_rows > 0 ? '#dc2626' : '#16a34a' }}>
                      {drilldownData?.duplicate_rows ?? '-'}
                    </p>
                  </div>
                  <div style={{ padding: '1rem', backgroundColor: 'var(--muted)', borderRadius: 'var(--radius)' }}>
                    <h3>Total Rows</h3>
                    <p style={{ fontSize: '1.5rem', fontWeight: 600, color: 'var(--foreground)' }}>{selectedAsset.total_rows}</p>
                  </div>
                </div>

                {/* History Chart */}
                {historyData.length > 0 && (
                  <div style={{ marginBottom: '2rem', height: '200px' }}>
                    <h3 style={{ marginBottom: '1rem' }}>Quality Trend History</h3>
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={historyData} margin={{ top: 5, right: 20, left: -20, bottom: 5 }}>
                        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
                        <XAxis dataKey="formatted_date" stroke="var(--muted-foreground)" fontSize={12} tickLine={false} axisLine={false} />
                        <YAxis domain={[0, 100]} stroke="var(--muted-foreground)" fontSize={12} tickLine={false} axisLine={false} />
                        <Tooltip contentStyle={{ borderRadius: '8px', border: '1px solid var(--border)' }} />
                        <Line type="monotone" dataKey="score" stroke="var(--primary)" strokeWidth={3} dot={{ r: 4 }} activeDot={{ r: 6 }} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                )}

                {/* Outliers */}
                {drilldownData && Object.keys(drilldownData.outliers || {}).length > 0 && (
                  <div style={{ marginBottom: '2rem' }}>
                    <h3 style={{ marginBottom: '1rem', color: '#dc2626' }}>Statistical Outliers (|Z| &gt; 3)</h3>
                    <ul style={{ listStyleType: 'none', padding: 0 }}>
                      {Object.entries(drilldownData.outliers).map(([col, count]) => (
                        <li key={col} style={{ padding: '0.75rem', border: '1px solid var(--border)', borderRadius: 'var(--radius)', marginBottom: '0.5rem', display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ fontWeight: 500 }}>{col}</span>
                          <span style={{ color: '#dc2626', fontWeight: 600 }}>{String(count)} extreme values</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Failed Expectations */}
                {drilldownData && drilldownData.failed_expectations?.length > 0 && (
                  <div>
                    <h3 style={{ marginBottom: '1rem', color: '#dc2626' }}>Rule Violations ({drilldownData.failed_expectations.length})</h3>
                    <div style={{ display: 'grid', gap: '1rem' }}>
                      {drilldownData.failed_expectations.map((rule: any, idx: number) => {
                        const expectationType = rule.expectation_config?.expectation_type || rule.expectation_config?.type || "Custom Validator";
                        const kwargs = rule.expectation_config?.kwargs || {};
                        const colName = kwargs.column || "Dataset";
                        let unexpectedList = rule.result?.partial_unexpected_list || rule.result?.unexpected_list || [];
                        
                        // Rule Prefix
                        const isGx = expectationType.startsWith('expect_');
                        const prefix = isGx ? `GX: '${expectationType}'` : `Custom Rule: '${expectationType}'`;

                        // English Explanation Mapping & Filtering false-positive type upcasts
                        let explanation = `Column '${colName}' failed the '${expectationType}' validation.`;
                        
                        if (expectationType === 'expect_column_values_to_be_of_type') {
                          explanation = `The column '${colName}' was strictly expected to contain exclusively '${kwargs.type_}' data. However, incompatible values were found causing the entire column to fail type validation.`;
                          
                          // If it's a numeric expectation, GX flags perfectly good numbers as strings if 
                          // the column was upcast by pandas. Let's filter the UI list to show the *actual* culprits.
                          if (kwargs.type_?.includes('int') || kwargs.type_?.includes('float')) {
                             unexpectedList = unexpectedList.filter((v: any) => isNaN(Number(v)) && String(v).trim() !== '');
                          }
                        } else if (expectationType === 'expect_column_values_to_not_be_null') {
                          explanation = `Universal null check enforced. The column '${colName}' was expected to have NO missing data, but empty/null rows were detected.`;
                          unexpectedList = unexpectedList.filter((v: any) => v === null || v === undefined || String(v).trim() === '' || String(v).toLowerCase() === 'nan');
                        } else if (expectationType === 'expect_column_to_exist') {
                          explanation = `Schema validation enforced. The required column '${colName}' is missing entirely from the dataset.`;
                        } else if (expectationType === 'expect_column_values_to_not_be_in_set') {
                          explanation = `Forbidden placeholder detected. The column '${colName}' contained values from the restricted list: ['null', 'n/a', 'nan', 'NULL', 'N/A', 'NaN']. These were flagged as invalid data.`;
                        } else if (expectationType === 'expect_column_values_to_match_regex') {
                          explanation = `Strict text validation enforced. The column '${colName}' was expected to contain meaningful text, but cells containing only whitespace, empty strings, or invalid date formats were found.`;
                        } else if (expectationType === 'expect_column_values_to_be_in_type_list') {
                          explanation = `Numeric safety enforced. The column '${colName}' was expected to contain valid numbers (e.g. integers or decimals), but text characters or symbols (like '$' or ',') were found.`;
                        } else if (expectationType === 'expect_compound_columns_to_be_unique') {
                          explanation = `Exact duplicate rows detected. These rows are completely identical across all columns and have been penalized.`;
                        }

                        // Fallback if unexpectedList is empty after heuristic filtering
                        const displayList = unexpectedList.length > 0 ? unexpectedList : (rule.result?.partial_unexpected_list || []).slice(0, 5);

                        return (
                          <div key={idx} style={{ padding: '1.25rem', border: '1px solid #fca5a5', backgroundColor: '#fef2f2', borderRadius: 'var(--radius)' }}>
                            <div className="flex items-center justify-between mb-3 border-b border-red-200 pb-3" style={{ borderBottomColor: '#fecaca', paddingBottom: '0.75rem', marginBottom: '0.75rem', borderBottomWidth: '1px', borderBottomStyle: 'solid' }}>
                              <div className="flex items-center gap-3">
                                <span style={{ fontWeight: 700, color: '#991b1b', fontSize: '1.1rem' }}>{colName}</span>
                                <span style={{ fontSize: '0.75rem', fontFamily: 'monospace', color: 'white', backgroundColor: '#991b1b', padding: '0.1rem 0.4rem', borderRadius: '4px' }}>
                                  {prefix}
                                </span>
                              </div>
                              {rule.result?.unexpected_count && (
                                <span style={{ color: '#b91c1c', fontWeight: 600, fontSize: '0.9rem' }}>
                                  {rule.result.unexpected_count} Failures ({rule.result.unexpected_percent?.toFixed(1)}%)
                                </span>
                              )}
                            </div>
                            
                            <p style={{ color: '#7f1d1d', margin: '0 0 1rem 0', fontSize: '0.95rem', lineHeight: 1.5 }}>
                              {explanation}
                            </p>

                            {/* Row Level Logs */}
                            {displayList.length > 0 && (
                              <div style={{ backgroundColor: '#1e293b', borderRadius: 'var(--radius)', padding: '0.75rem', fontFamily: 'monospace', fontSize: '0.8rem', color: '#e2e8f0', maxHeight: '150px', overflowY: 'auto' }}>
                                <div style={{ marginBottom: '0.5rem', color: '#94a3b8', fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Row Violation Logs</div>
                                {displayList.map((val: any, vIdx: number) => (
                                  <div key={vIdx} style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.25rem' }}>
                                    <span style={{ color: '#ef4444' }}>[Error]</span>
                                    <span>Row contained invalid format: </span>
                                    <span style={{ color: '#fbbf24' }}>"{val === null ? 'null' : String(val)}"</span>
                                  </div>
                                ))}
                                {rule.result?.unexpected_count > displayList.length && (
                                  <div style={{ color: '#94a3b8', marginTop: '0.5rem', fontStyle: 'italic' }}>
                                    ...and {rule.result.unexpected_count - displayList.length} more unlogged violations.
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )}

                {drilldownData && (drilldownData.total_failed_count || 0) === 0 && Object.keys(drilldownData.outliers || {}).length === 0 && (
                  <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--muted-foreground)' }}>
                    <CheckCircle size={48} color="#16a34a" style={{ margin: '0 auto 1rem auto' }} />
                    <p>Perfect score! No rule violations or outliers found.</p>
                  </div>
                )}

                {drilldownData && (drilldownData.total_failed_count || 0) > 0 && drilldownData.failed_expectations?.length === 0 && (
                  <div style={{ textAlign: 'center', padding: '2rem', background: '#fff7ed', borderRadius: '12px', border: '1px solid #ffedd5', color: '#9a3412' }}>
                    <AlertTriangle size={48} color="#f97316" style={{ margin: '0 auto 1rem auto' }} />
                    <p style={{ fontWeight: 600 }}>Detailed results unavailable</p>
                    <p style={{ fontSize: '0.875rem' }}>
                      {drilldownData.parsing_error 
                        ? "The raw validation data was too large and became corrupted. "
                        : "Detailed logs were truncated during processing. "}
                      However, the system still detected <strong>{drilldownData.total_failed_count}</strong> rule violations which impacted the quality score.
                    </p>
                  </div>
                )}

                {/* Extracted Document Download Link (If applicable) */}
                {(selectedAsset.source_type === "LandingAI" || selectedAsset.source_name === "LandingAI") && (
                  <div style={{ marginTop: '2rem', padding: '1rem', backgroundColor: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 'var(--radius)' }}>
                     <div className="flex items-center justify-between">
                       <div>
                         <h4 style={{ color: '#166534', margin: '0 0 0.25rem 0' }}>Landing AI Extraction Artifacts</h4>
                         <p style={{ color: '#15803d', margin: 0, fontSize: '0.875rem' }}>Access both the structured table and raw optical text.</p>
                       </div>
                       <div style={{ display: 'flex', gap: '1rem' }}>
                         <button 
                           onClick={() => {
                             const base = selectedAsset.asset_name.replace(/(_extracted\.csv|_parsed\.md)$/, "");
                             window.open(`${API_URL}/api/documents/extracted/${base}_parsed.md`, '_blank');
                           }}
                           className="btn" 
                           style={{ backgroundColor: '#16a34a', color: 'white', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                         >
                           <Download size={16} /> Raw Markdown
                         </button>
                         <button 
                           onClick={() => {
                             const base = selectedAsset.asset_name.replace(/(_extracted\.csv|_parsed\.md)$/, "");
                             window.open(`${API_URL}/api/documents/extracted/${base}_extracted.csv`, '_blank');
                           }}
                           className="btn" 
                           style={{ backgroundColor: '#15803d', color: 'white', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                         >
                           <Download size={16} /> Tabular CSV
                         </button>
                       </div>
                     </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="flex-col gap-4">
                {(explorerData.columns.length === 0 && !selectedAsset?.asset_name?.toLowerCase().endsWith('.md') && !selectedAsset?.asset_name?.toLowerCase().endsWith('.json')) ? (
                  <p style={{ textAlign: 'center', padding: '3rem', color: 'var(--muted-foreground)' }}>No data available for preview. Please wait or check the logs.</p>
                ) : (
                  <div>
                    {/* Toolbar */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                      <div className="flex items-center gap-4">
                        <p style={{ margin: 0, fontWeight: 500, color: 'var(--muted-foreground)' }}>Previewing Data Snapshot</p>
                        <div style={{ display: 'flex', gap: '0.25rem', background: 'var(--muted)', padding: '0.25rem', borderRadius: 'var(--radius)' }}>
                          <button onClick={() => setExplorerViewMode('grid')} style={{ padding: '0.25rem 0.75rem', border: 'none', background: explorerViewMode === 'grid' ? 'var(--background)' : 'transparent', borderRadius: '4px', cursor: 'pointer', fontWeight: 500 }}>Grid View</button>
                          <button onClick={() => setExplorerViewMode('raw')} style={{ padding: '0.25rem 0.75rem', border: 'none', background: explorerViewMode === 'raw' ? 'var(--background)' : 'transparent', borderRadius: '4px', cursor: 'pointer', fontWeight: 500 }}>Raw Editor</button>
                        </div>
                      </div>
                      <button 
                        className="btn btn-primary"
                        onClick={() => setShowGovModal(true)}
                        disabled={!hasEdits}
                      >
                        Save Changes
                      </button>
                    </div>
                    
                    {/* Interactive Editor Container */}
                    {explorerViewMode === 'raw' ? (
                      <div style={{ display: 'flex', flexDirection: 'column', border: '1px solid var(--border)', borderRadius: 'var(--radius)', height: '500px', backgroundColor: '#1e293b' }}>
                         {jsonError && (
                           <div style={{ padding: '0.75rem', backgroundColor: '#fef2f2', color: '#9f1239', borderBottom: '1px solid #fecaca', fontSize: '0.85rem', fontWeight: 500 }}>
                             ⚠️ {jsonError}
                           </div>
                         )}
                         <textarea
                           value={rawJsonText}
                           onChange={(e) => {
                             setRawJsonText(e.target.value);
                             setHasEdits(true);
                             if (selectedAsset?.asset_name?.toLowerCase().endsWith('.json')) {
                               try {
                                 const parsed = JSON.parse(e.target.value);
                                 if (Array.isArray(parsed)) {
                                   setExplorerData({ ...explorerData, rows: parsed });
                                   setJsonError("");
                                 } else {
                                   setJsonError("Root element must be an array of structural objects.");
                                 }
                               } catch (err: any) {
                                 setJsonError(`JSON Syntax Error: ${err.message}`);
                               }
                             }
                           }}
                           style={{ flex: 1, width: '100%', padding: '1rem', border: 'none', backgroundColor: 'transparent', color: '#e2e8f0', fontFamily: 'monospace', fontSize: '0.9rem', outline: 'none', resize: 'none' }}
                           spellCheck={false}
                         />
                      </div>
                    ) : (
                      <div style={{ overflowX: 'auto', border: '1px solid var(--border)', borderRadius: 'var(--radius)', maxHeight: '60vh' }}>
                        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.85rem' }}>
                          <thead style={{ position: 'sticky', top: 0, backgroundColor: 'var(--muted)', zIndex: 10, boxShadow: '0 1px 2px rgba(0,0,0,0.1)' }}>
                            <tr>
                              {explorerData.columns.map((col, cIdx) => (
                                <th key={cIdx} style={{ padding: '0.75rem', borderBottom: '1px solid var(--border)', fontWeight: 600 }}>{col}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {explorerData.rows.map((row, rIdx) => (
                              <tr key={rIdx} style={{ borderBottom: '1px solid var(--border)' }}>
                                {explorerData.columns.map((col, cIdx) => (
                                  <td key={cIdx} style={{ padding: 0 }}>
                                    <input 
                                      type="text" 
                                      value={row[col] === null ? '' : row[col]} 
                                      onChange={(e) => {
                                        const newRows = [...explorerData.rows];
                                        newRows[rIdx] = { ...newRows[rIdx], [col]: e.target.value };
                                        setExplorerData({ ...explorerData, rows: newRows });
                                        setHasEdits(true);
                                      }}
                                      style={{ width: '100%', minWidth: '120px', padding: '0.75rem', border: 'none', backgroundColor: 'transparent', color: 'var(--foreground)', outline: 'none', transition: 'background-color 0.2s' }}
                                      onFocus={(e) => e.target.style.backgroundColor = 'var(--muted)'}
                                      onBlur={(e) => e.target.style.backgroundColor = 'transparent'}
                                    />
                                  </td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Governance Audit Modal */}
      {showGovModal && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(15, 23, 42, 0.8)', zIndex: 60, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div className="card" style={{ width: '100%', maxWidth: '450px' }}>
            <div className="flex items-center gap-3 mb-4">
              <FileText size={24} color="var(--primary)" />
              <h3 style={{ margin: 0 }}>Governance Audit Log</h3>
            </div>
            <p style={{ marginBottom: '1.5rem', fontSize: '0.9rem', color: 'var(--muted-foreground)' }}>
              You are modifying the raw asset data. Please provide your identity and reason for the change to satisfy governance compliance.
            </p>
            
            <div style={{ marginBottom: '1rem' }}>
              <label style={{ display: 'block', fontWeight: 500, marginBottom: '0.5rem', fontSize: '0.9rem' }}>Your Name / ID</label>
              <input type="text" value={govName} onChange={e => setGovName(e.target.value)} placeholder="e.g., Data Steward Jane" style={{ width: '100%', padding: '0.75rem', borderRadius: 'var(--radius)', border: '1px solid var(--border)', backgroundColor: 'var(--background)', color: 'var(--foreground)', outline: 'none' }} />
            </div>
            
            <div style={{ marginBottom: '1.5rem' }}>
              <label style={{ display: 'block', fontWeight: 500, marginBottom: '0.5rem', fontSize: '0.9rem' }}>Reason for Change</label>
              <textarea value={govReason} onChange={e => setGovReason(e.target.value)} placeholder="e.g., Fixing negative revenue outliers found during QA" rows={3} style={{ width: '100%', padding: '0.75rem', borderRadius: 'var(--radius)', border: '1px solid var(--border)', backgroundColor: 'var(--background)', color: 'var(--foreground)', outline: 'none', resize: 'none' }} />
            </div>
            
            <div style={{ display: 'flex', gap: '1rem', justifyContent: 'flex-end' }}>
              <button onClick={() => setShowGovModal(false)} className="btn" style={{ backgroundColor: 'transparent', color: 'var(--foreground)' }}>Cancel</button>
              <button 
                onClick={async () => {
                  setIsSaving(true);
                  try {
                    // If we made edits in raw mode or grid mode, determine payload
                    const payload = { 
                      edited_by: govName, 
                      edit_note: govReason, 
                      rows: explorerData.rows,
                      raw_text: explorerViewMode === 'raw' ? rawJsonText : null
                    };
                    
                    const res = await fetch(`${API_URL}/api/assets/${selectedAsset?.asset_id}/data`, {
                      method: 'PUT',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify(payload)
                    });
                    if (!res.ok) throw new Error("Failed to save data");
                    
                    setShowGovModal(false);
                    setSelectedAsset(null); 
                    setGovName('');
                    setGovReason('');
                    fetchData(); 
                  } catch(e) {
                    alert("Save failed. Check console.");
                  } finally {
                    setIsSaving(false);
                  }
                }} 
                className="btn btn-primary"
                disabled={isSaving || !govName.trim() || !govReason.trim()}
              >
                {isSaving ? 'Submitting...' : 'Confirm & Save'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Header Metrics */}
      <div className="grid grid-cols-4 mb-6" style={{ marginTop: '1rem' }}>
        <div className="card flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <h3>Total Assets</h3>
            <Database className="upload-icon" size={20} />
          </div>
          <p style={{ fontSize: '2rem', fontWeight: 700, color: 'var(--foreground)' }}>{kpis?.total_assets ?? '-'}</p>
        </div>
        
        <div className="card flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <h3>Avg Quality</h3>
            <Activity className="upload-icon" size={20} />
          </div>
          <p style={{ fontSize: '2rem', fontWeight: 700, color: 'var(--foreground)' }}>
            {kpis?.avg_quality_score !== undefined ? `${kpis.avg_quality_score}%` : '-'}
          </p>
        </div>

        <div className="card flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <h3>Rank A Assets</h3>
            <CheckCircle className="upload-icon" size={20} color="#16a34a" />
          </div>
          <p style={{ fontSize: '2rem', fontWeight: 700, color: '#16a34a' }}>{kpis?.rank_a_count ?? '-'}</p>
        </div>

        <div className="card flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <h3>Needs Review</h3>
            <AlertTriangle className="upload-icon" size={20} color="#dc2626" />
          </div>
          <p style={{ fontSize: '2rem', fontWeight: 700, color: '#dc2626' }}>{kpis?.below_gate_count ?? '-'}</p>
        </div>
      </div>

      <div className="grid grid-cols-2 mb-6">
        {/* Ingestion Component */}
        <div className="card flex flex-col">
          <div className="flex items-center justify-between mb-4">
            <h2 style={{ margin: 0 }}>Data Ingestion</h2>
            <div style={{ display: 'flex', gap: '0.5rem', backgroundColor: 'var(--muted)', padding: '0.25rem', borderRadius: 'var(--radius)' }}>
              <button 
                onClick={() => { setIngestMode('local'); setUploadStatus(''); setUploadState('idle'); }}
                style={{ padding: '0.25rem 0.75rem', borderRadius: '0.25rem', border: 'none', cursor: 'pointer', fontSize: '0.85rem', fontWeight: 500, backgroundColor: ingestMode === 'local' ? 'var(--background)' : 'transparent', color: ingestMode === 'local' ? 'var(--foreground)' : 'var(--muted-foreground)', boxShadow: ingestMode === 'local' ? 'var(--shadow)' : 'none' }}
              >
                Local File
              </button>
              <button 
                onClick={() => { setIngestMode('api'); setUploadStatus(''); setUploadState('idle'); }}
                style={{ padding: '0.25rem 0.75rem', borderRadius: '0.25rem', border: 'none', cursor: 'pointer', fontSize: '0.85rem', fontWeight: 500, backgroundColor: ingestMode === 'api' ? 'var(--background)' : 'transparent', color: ingestMode === 'api' ? 'var(--foreground)' : 'var(--muted-foreground)', boxShadow: ingestMode === 'api' ? 'var(--shadow)' : 'none' }}
              >
                API Source
              </button>
            </div>
          </div>

          {ingestMode === 'local' ? (
            <>
              <p className="mb-6">Upload a local dataset. 1MB limit applies.</p>
              <div 
                className="upload-zone"
                ref={dropZoneRef}
                onDragOver={onDragOver}
                onDragLeave={onDragLeave}
                onDrop={onDrop}
                onClick={() => document.getElementById('fileUpload')?.click()}
              >
                <UploadCloud size={48} className="upload-icon" />
                <div>
                  <p style={{ color: 'var(--foreground)', fontWeight: 500, fontSize: '1rem' }}>
                    {file ? file.name : "Click or drag file to upload"}
                  </p>
                  <p>SVG, CSV, JSON, PDF Images (max. 1MB)</p>
                </div>
                <input type="file" id="fileUpload" onChange={handleFileChange} style={{ display: 'none' }} />
              </div>
            </>
          ) : (
            <>
              <p className="mb-4">Select an external API connection to pull data from automatically.</p>
              
              <div className="flex gap-4 mb-6">
                <div 
                  onClick={() => setApiSource('alpha-vantage')}
                  style={{ flex: 1, padding: '1rem', border: apiSource === 'alpha-vantage' ? '2px solid var(--primary)' : '1px solid var(--border)', borderRadius: 'var(--radius)', cursor: 'pointer', backgroundColor: apiSource === 'alpha-vantage' ? 'rgba(59, 130, 246, 0.05)' : 'transparent', transition: 'all 0.2s' }}
                >
                  <Activity size={24} color={apiSource === 'alpha-vantage' ? 'var(--primary)' : 'var(--muted-foreground)'} style={{ marginBottom: '0.5rem' }} />
                  <div style={{ fontWeight: 600, color: 'var(--foreground)' }}>Alpha Vantage</div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--muted-foreground)' }}>Stock Market Data</div>
                </div>

                <div 
                  style={{ flex: 1, padding: '1rem', border: '1px dashed var(--border)', borderRadius: 'var(--radius)', opacity: 0.6, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}
                >
                  <div style={{ fontWeight: 500, color: 'var(--muted-foreground)' }}>+ Add API Source</div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--muted-foreground)' }}>(Coming soon)</div>
                </div>
              </div>

              {apiSource === 'alpha-vantage' && (
                <div style={{ marginBottom: '1rem' }}>
                  <label style={{ display: 'block', fontWeight: 500, marginBottom: '0.5rem', fontSize: '0.9rem' }}>Stock Ticker Symbol</label>
                  <input 
                    type="text" 
                    value={apiSymbol} 
                    onChange={(e) => setApiSymbol(e.target.value.toUpperCase())}
                    placeholder="e.g., AAPL, MSFT, TSLA" 
                    style={{ width: '100%', padding: '0.75rem', borderRadius: 'var(--radius)', border: '1px solid var(--border)', backgroundColor: 'var(--background)', color: 'var(--foreground)', outline: 'none' }}
                  />
                </div>
              )}
            </>
          )}

          <div className="flex items-center justify-between mt-6">
            <div className="flex items-center gap-2">
              {uploadState === 'success' && <Check size={18} color="#16a34a" />}
              {uploadState === 'error' && <AlertCircle size={18} color="#dc2626" />}
              {(uploadState === 'uploading' || uploadStatus) && (
                <span className={uploadState === 'error' ? 'error-text' : 'status-text'} style={{margin: 0, display: 'flex', alignItems: 'center', gap: '0.4rem'}}>
                  {uploadState === 'uploading' && <span className="spin" style={{fontSize: '1.1rem'}}>⚙️</span>}
                  {uploadStatus}
                </span>
              )}
            </div>
            <button 
              className="btn btn-primary"
              onClick={ingestMode === 'local' ? uploadSelectedFile : triggerApiIngestion}
              disabled={uploadState === 'uploading' || (ingestMode === 'local' ? !file : !apiSymbol.trim())}
            >
              Start Pipeline
            </button>
          </div>
        </div>

        {/* Chart Component */}
        <div className="card flex flex-col">
          <h2>Asset Health Snapshot</h2>
          <p className="mb-6">Click a bar to view detailed metrics and history.</p>
          <div style={{ flex: 1, minHeight: '250px', marginLeft: '-20px' }}>
            {assets.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={assets} layout="vertical" margin={{ top: 0, right: 30, left: 30, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="var(--border)" />
                  <XAxis type="number" domain={[0, 100]} stroke="var(--muted-foreground)" fontSize={12} tickLine={false} axisLine={false} />
                  <YAxis dataKey="asset_name" type="category" stroke="var(--muted-foreground)" fontSize={12} tickLine={false} axisLine={false} />
                  <Tooltip 
                    contentStyle={{ borderRadius: '8px', border: '1px solid var(--border)', boxShadow: 'var(--shadow)' }}
                    cursor={{fill: 'var(--muted)'}}
                  />
                  <Bar 
                    dataKey="score" 
                    radius={[0, 4, 4, 0]} 
                    barSize={24}
                    onClick={(data: any) => {
                      const id = data?.payload?.asset_id || data?.asset_id;
                      if(id) {
                         const match = assets.find(a => a.asset_id === id);
                         if (match) openDrilldown(match);
                      }
                    }}
                    style={{ cursor: 'pointer' }}
                  >
                    {assets.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.score >= 90 ? '#3b82f6' : entry.score >= 70 ? '#f59e0b' : '#ef4444'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex items-center justify-center" style={{ height: '100%', color: 'var(--muted-foreground)' }}>
                Loading visualization...
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Tables Section */}
      <div className="grid grid-cols-2">
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
          {/* Landing AI Document Pipeline */}
          <div className="card" style={{ flex: 1, maxHeight: '430px', display: 'flex', flexDirection: 'column' }}>
            <div className="flex items-center justify-between mb-4">
              <h2>Landing AI Documents</h2>
              <FileText size={20} className="upload-icon" />
            </div>
            <div className="table-container" style={{ flex: 1, overflowY: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.85rem' }}>
                <thead style={{ position: 'sticky', top: 0, backgroundColor: 'var(--muted)', zIndex: 10, boxShadow: '0 1px 2px rgba(0,0,0,0.1)' }}>
                  <tr>
                    <th style={{ padding: '0.75rem', borderBottom: '1px solid var(--border)' }}>Status</th>
                    <th style={{ padding: '0.75rem', borderBottom: '1px solid var(--border)' }}>Document</th>
                    <th style={{ padding: '0.75rem', borderBottom: '1px solid var(--border)' }}>Score</th>
                    <th style={{ padding: '0.75rem', borderBottom: '1px solid var(--border)' }}>Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {assets.filter(a => a.source_type === 'LandingAI' || a.source_name === 'LandingAI').map((a, i) => (
                    <tr key={i} onClick={() => openDrilldown(a)} style={{ cursor: 'pointer', transition: 'background-color 0.2s', borderBottom: '1px solid var(--border)' }} onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'var(--muted)'} onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'transparent'}>
                      <td style={{ padding: '0.75rem' }}><span className={`badge ${a.rank === 'A' ? 'badge-success' : a.rank === 'B' ? 'badge-info' : a.rank === 'C' ? 'badge-warning' : 'badge-danger'}`}>{a.rank}</span></td>
                      <td style={{ padding: '0.75rem', fontWeight: 500, color: 'var(--primary)' }}>{a.asset_name}</td>
                      <td style={{ padding: '0.75rem' }}>{a.score === 100 && a.format === 'md' ? 'N/A (Raw Text)' : `${a.score.toFixed(1)}%`}</td>
                      <td style={{ padding: '0.75rem', color: 'var(--muted-foreground)' }}>{new Date(a.evaluated_at).toLocaleDateString()}</td>
                    </tr>
                  ))}
                  {assets.filter(a => a.source_type === 'LandingAI' || a.source_name === 'LandingAI').length === 0 && (
                     <tr><td colSpan={4} style={{ padding: '0.75rem', textAlign: 'center', color: 'var(--muted-foreground)' }}>No documents processed yet.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Tabular Pipeline Registry */}
          <div className="card" style={{ flex: 1, maxHeight: '430px', display: 'flex', flexDirection: 'column' }}>
            <div className="flex items-center justify-between mb-4">
              <h2>Tabular Pipeline Registry</h2>
              <Database size={20} className="upload-icon" />
            </div>
            <div className="table-container" style={{ flex: 1, overflowY: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.85rem' }}>
                <thead style={{ position: 'sticky', top: 0, backgroundColor: 'var(--muted)', zIndex: 10, boxShadow: '0 1px 2px rgba(0,0,0,0.1)' }}>
                  <tr>
                    <th style={{ padding: '0.75rem', borderBottom: '1px solid var(--border)' }}>Status</th>
                    <th style={{ padding: '0.75rem', borderBottom: '1px solid var(--border)' }}>Dataset</th>
                    <th style={{ padding: '0.75rem', borderBottom: '1px solid var(--border)' }}>Score</th>
                    <th style={{ padding: '0.75rem', borderBottom: '1px solid var(--border)' }}>Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {assets.filter(a => a.source_type !== 'LandingAI' && a.source_name !== 'LandingAI').map((a, i) => (
                    <tr key={i} onClick={() => openDrilldown(a)} style={{ cursor: 'pointer', transition: 'background-color 0.2s', borderBottom: '1px solid var(--border)' }} onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'var(--muted)'} onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'transparent'}>
                      <td style={{ padding: '0.75rem' }}><span className={`badge ${a.rank === 'A' ? 'badge-success' : a.rank === 'B' ? 'badge-info' : a.rank === 'C' ? 'badge-warning' : 'badge-danger'}`}>{a.rank}</span></td>
                      <td style={{ padding: '0.75rem', fontWeight: 500, color: 'var(--primary)' }}>{a.asset_name}</td>
                      <td style={{ padding: '0.75rem' }}>{a.score.toFixed(1)}%</td>
                      <td style={{ padding: '0.75rem', color: 'var(--muted-foreground)' }}>{new Date(a.evaluated_at).toLocaleDateString()}</td>
                    </tr>
                  ))}
                  {assets.filter(a => a.source_type !== 'LandingAI' && a.source_name !== 'LandingAI').length === 0 && (
                     <tr><td colSpan={4} style={{ padding: '0.75rem', textAlign: 'center', color: 'var(--muted-foreground)' }}>No tabular datasets processed yet.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div className="card" style={{ maxHeight: '884px', display: 'flex', flexDirection: 'column' }}>
           <div className="flex items-center justify-between mb-4">
            <h2>Governance Log</h2>
            <Activity size={20} className="upload-icon" />
          </div>
          <div className="table-container" style={{ flex: 1, overflowY: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.85rem' }}>
              <thead style={{ position: 'sticky', top: 0, backgroundColor: 'var(--muted)', zIndex: 10, boxShadow: '0 1px 2px rgba(0,0,0,0.1)' }}>
                <tr>
                  <th style={{ padding: '0.75rem', borderBottom: '1px solid var(--border)' }}>User</th>
                  <th style={{ padding: '0.75rem', borderBottom: '1px solid var(--border)' }}>Asset</th>
                  <th style={{ padding: '0.75rem', borderBottom: '1px solid var(--border)' }}>Note</th>
                  <th style={{ padding: '0.75rem', borderBottom: '1px solid var(--border)' }}>Timestamp</th>
                </tr>
              </thead>
              <tbody>
                {audits.map((au) => {
                  let filename = au.file_path ? au.file_path.split('/').pop() : 'System Processing';
                  if (filename && typeof filename === 'string') {
                    // Strip the initial UUID prefix and the _revYYYYMMDDHHMMSS suffix
                    filename = filename.replace(/^[0-9a-fA-F-]+_/, '').replace(/_rev\d{14}/, '');
                  }
                  return (
                    <tr key={au.revision_id} style={{ borderBottom: '1px solid var(--border)' }}>
                      <td style={{ padding: '0.75rem', fontWeight: 500 }}>{au.edited_by}</td>
                      <td style={{ padding: '0.75rem', color: 'var(--primary)', fontWeight: 600 }}>{filename}</td>
                      <td style={{ padding: '0.75rem', color: 'var(--muted-foreground)' }}>{au.edit_note || 'Pipeline Ingestion'}</td>
                      <td style={{ padding: '0.75rem', color: 'var(--muted-foreground)' }}>
                        {new Date(au.edited_at).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}
                      </td>
                    </tr>
                  )
                })}
                {audits.length === 0 && (
                  <tr>
                    <td colSpan={4} style={{ padding: '0.75rem', textAlign: 'center', color: 'var(--muted-foreground)' }}>No recent activity.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Deletion Governance Modal */}
      {showDeleteModal && (
        <div style={{
          position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
          backgroundColor: 'rgba(15, 23, 42, 0.7)', backdropFilter: 'blur(8px)',
          zIndex: 100, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '2rem'
        }}>
          <div className="card" style={{ maxWidth: '500px', width: '100%', border: '2px solid #ef4444' }}>
            <div className="flex items-center gap-3 mb-4" style={{ color: '#ef4444' }}>
              <AlertTriangle size={32} />
              <h2 style={{ margin: 0 }}>Governed Deletion</h2>
            </div>
            <p style={{ marginBottom: '1.5rem', color: 'var(--muted-foreground)' }}>
              You are about to <span style={{ color: '#ef4444', fontWeight: 700 }}>SOFT-DELETE</span> this entry. It will be hidden from all dashboards, but the file remains in S3 and its removal will be permanently logged in the governance audit trail.
            </p>
            
            <div className="flex-col gap-4 mb-6">
              <div>
                <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 500 }}>Confirm your Identity (Full Name)</label>
                <input 
                  type="text" 
                  className="input" 
                  value={govName}
                  onChange={(e) => setGovName(e.target.value)}
                  placeholder="e.g. Data Steward Alex"
                />
              </div>
              <div>
                <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 500 }}>Reason for Deletion</label>
                <textarea 
                  className="input" 
                  style={{ minHeight: '80px' }}
                  value={govReason}
                  onChange={(e) => setGovReason(e.target.value)}
                  placeholder="e.g. Obsolete extraction or duplicate ingest..."
                />
              </div>
            </div>

            <div style={{ display: 'flex', gap: '1rem', justifyContent: 'flex-end' }}>
              <button className="btn btn-secondary" onClick={() => setShowDeleteModal(false)}>Cancel</button>
              <button 
                className="btn" 
                style={{ backgroundColor: '#ef4444', color: 'white' }}
                disabled={!govName || !govReason || isSaving}
                onClick={async () => {
                  if (!selectedAsset) return;
                  setIsSaving(true);
                  try {
                    const res = await fetch(`${API_URL}/api/assets/${selectedAsset.asset_id}`, {
                      method: 'DELETE',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ edited_by: govName, edit_note: govReason })
                    });
                    if (res.ok) {
                      setShowDeleteModal(false);
                      setSelectedAsset(null);
                      fetchData();
                    } else {
                      alert("Deletion failed. Check server logs.");
                    }
                  } catch (e) {
                    console.error(e);
                  } finally {
                    setIsSaving(false);
                  }
                }}
              >
                {isSaving ? "Logging Deletion..." : "Commit Deletion"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
