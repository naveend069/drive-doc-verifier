// Index.tsx
import React, { useEffect, useMemo, useState } from "react";
import axios from "axios";

// In src/pages/Index.tsx
const API = "https://drive-doc-verifier.onrender.com";

interface VerifyResult {
  name: string;
  serial_no: string;
  status: "Complete" | "Incomplete";
  found_files: string[];
  missing_files: string[];
  drive_link?: string | null;
  file_map?: { [label: string]: string };
}

// FIX UTILITY: Robust function to ensure the database field is always treated as a JS Array
const parseArray = (data: any): string[] => {
    if (Array.isArray(data)) return data;
    if (typeof data === 'string') {
        // Handle common Supabase/PostgreSQL string array formats like "{item1,item2}"
        if (data.startsWith('{') && data.endsWith('}')) {
            return data.substring(1, data.length - 1).split(',');
        }
        // Handle JSON strings like "[\"item1\",\"item2\"]"
        try {
            const parsed = JSON.parse(data);
            if (Array.isArray(parsed)) return parsed;
        } catch {
            // failed to parse, fall through
        }
    }
    return []; // Return an empty array if not array or parsable string
};

// FIX UTILITY: Function to normalize any incoming student result
const normalizeResult = (r: any): VerifyResult => ({
    name: r.name,
    serial_no: r.serial_no,
    status: (r.status as "Complete" | "Incomplete") || "Incomplete",
    found_files: parseArray(r.found_files || []),
    missing_files: parseArray(r.missing_files || []),
    drive_link: r.drive_link ?? null,
    file_map: r.file_map ?? {},
});


export default function Index(): JSX.Element {
  const [form, setForm] = useState({ name: "", serial_no: "", drive_link: "" });
  const [loading, setLoading] = useState(false);
  const [students, setStudents] = useState<VerifyResult[]>([]);
  const [result, setResult] = useState<VerifyResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<"all" | "complete" | "incomplete">("all");
  const [sortBy, setSortBy] = useState<"name" | "serial_no" | "status">("name");

  const entriesPerPage = 8;
  const [page, setPage] = useState(1);

  // Use Memo for the required codes list
  const requiredCodes: { code: string; label: string }[] = useMemo(() => {
    const requiredLabels = ["photo", "aadhar", "community", "marksheet", "tc"];
    return requiredLabels.map((label, index) => ({
        code: `S${index + 1}`,
        label: label
    }));
  }, []);

  const fetchStudents = async () => {
    try {
      const res = await axios.get(`${API}/students`);
      const rows = res.data.data || [];
      // Use the normalization utility for all fetched rows
      const normalized: VerifyResult[] = rows.map(normalizeResult); 
      setStudents(normalized);
      setError(null);
    } catch (e) {
      console.error("fetch students error", e);
      setError("Unable to load students. Check if the backend is running at " + API);
    }
  };

  useEffect(() => {
    fetchStudents();
  }, []);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [e.target.name]: e.target.value });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setResult(null);
    setLoading(true);

    if (!form.name.trim() || !form.serial_no.trim() || !form.drive_link.trim()) {
      setError("Please fill all fields.");
      setLoading(false);
      return;
    }

    try {
      const res = await axios.post(`${API}/verify`, form);
      if (res.data.result) {
        // Use the normalization utility
        const newRecord: VerifyResult = normalizeResult(res.data.result); 
        
        // Handle update or addition to local state based on serial_no
        setStudents((prev) => {
            const existingIndex = prev.findIndex(s => s.serial_no === newRecord.serial_no);
            if (existingIndex > -1) {
                // If it exists (backend returned the existing record), update it
                return prev.map((s, index) => index === existingIndex ? newRecord : s);
            }
            return [newRecord, ...prev]; // Prepend new record
        });

        setResult(newRecord);
        setForm({ name: "", serial_no: "", drive_link: "" });
      } else if (res.data.error) {
         setError(res.data.error);
      } else {
         setError("Unexpected response from server.");
      }
    } catch (err) {
      console.error("verify error", err);
      setError("Failed to connect to backend.");
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (serial_no: string) => {
    if (!window.confirm(`Delete ${serial_no}?`)) return;
    try {
      await axios.delete(`${API}/delete/${encodeURIComponent(serial_no)}`);
      setStudents((prev) => prev.filter((s) => s.serial_no !== serial_no));
      if (result?.serial_no === serial_no) setResult(null);
    } catch (err) {
      console.error("delete error", err);
      setError("Failed to delete student. See console.");
    }
  };

  const handleRefresh = async (serial_no: string) => {
    try {
      const res = await axios.post(`${API}/refresh/${encodeURIComponent(serial_no)}`);
      if (res.data.updated) {
        // Use the normalization utility
        const updated: VerifyResult = normalizeResult(res.data.updated); 
        
        setStudents((prev) => prev.map((s) => (s.serial_no === serial_no ? updated : s)));
        if (result?.serial_no === serial_no) setResult(updated);
      } else {
        if (res.data.error) alert("Refresh error: " + res.data.error);
        setError(res.data.error || "Refresh failed");
      }
    } catch (err) {
      console.error("refresh error", err);
      alert("Failed to refresh — check console.");
    }
  };

  // Filtering + sorting (logic kept as is)
  const filtered = useMemo(() => {
    let out = [...students];
    if (search.trim()) {
      const q = search.toLowerCase();
      out = out.filter((s) => s.name.toLowerCase().includes(q) || s.serial_no.toLowerCase().includes(q));
    }
    if (filter !== "all") {
      const target = filter === "complete" ? "Complete" : "Incomplete";
      out = out.filter((s) => s.status === target);
    }
    out.sort((a, b) => {
      if (sortBy === "name") return a.name.localeCompare(b.name);
      if (sortBy === "serial_no") return a.serial_no.localeCompare(b.serial_no);
      return a.status.localeCompare(b.status);
    });
    return out;
  }, [students, search, filter, sortBy]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / entriesPerPage));
  const paginated = filtered.slice((page - 1) * entriesPerPage, page * entriesPerPage);

  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [totalPages, page]);

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto p-6 grid grid-cols-1 lg:grid-cols-6 gap-6">
        {/* Sidebar */}
        <aside className="lg:col-span-1 bg-white rounded shadow p-4 sticky top-6 h-fit">
          <h3 className="text-lg font-semibold mb-3">Required File Codes</h3>
          <ul className="text-sm space-y-2">
            {requiredCodes.map((c) => (
              <li key={c.code} className="flex items-center justify-between">
                <div>
                  <span className="font-medium">{c.code}</span>
                  <span className="text-gray-600 ml-2">{c.label}</span>
                </div>
              </li>
            ))}
          </ul>
          <p className="text-xs text-gray-500 mt-4">
            Files must be named containing the required document label OR starting with the S-code (e.g., <span className="font-semibold">S1.jpg</span> or <span className="font-semibold">passport photo.pdf</span>).
          </p>
        </aside>

        {/* Main */}
        <main className="lg:col-span-5">
          {/* Header */}
          <div className="flex items-center justify-between mb-6">
            <div>
              <h1 className="text-2xl font-semibold text-gray-900">RC TRUST — Verification</h1>
              <p className="text-sm text-gray-500">Verify & manage student documents</p>
            </div>
            <div>
              <button onClick={fetchStudents} className="px-3 py-2 border rounded bg-white">🔄 Refresh list</button>
            </div>
          </div>

          {/* Form + Result */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-6">
            <div className="md:col-span-1 bg-white p-4 rounded shadow">
              <h2 className="font-medium mb-2">Verify Student</h2>
              <form onSubmit={handleSubmit} className="space-y-3">
                <input name="name" value={form.name} onChange={handleChange} placeholder="Student name" className="w-full p-2 border rounded" required />
                <input name="serial_no" value={form.serial_no} onChange={handleChange} placeholder="Serial no" className="w-full p-2 border rounded" required />
                <input name="drive_link" value={form.drive_link} onChange={handleChange} placeholder="Drive folder link" className="w-full p-2 border rounded" required />
                <button disabled={loading} className="w-full py-2 bg-blue-600 text-white rounded">{loading ? "Verifying..." : "Verify"}</button>
                {error && <div className="text-sm text-red-600 mt-2">{error}</div>}
              </form>
            </div>

            <div className="md:col-span-2 bg-white p-4 rounded shadow">
              {result ? (
                <>
                  <div className="flex justify-between items-start">
                    <div>
                      <div className="font-semibold">{result.name} — {result.serial_no}</div>
                      <div className="text-xs text-gray-500">Status: <span className={result.status === "Complete" ? "text-green-600" : "text-red-600"}>{result.status}</span></div>
                    </div>
                    {result.drive_link && (
                      <a href={result.drive_link} target="_blank" rel="noreferrer" className="text-sm text-blue-600">Open Drive</a>
                    )}
                  </div>

                  <div className="mt-3 text-sm text-gray-700">
                    <div><strong>Found:</strong> {result.found_files.join(", ") || "None"}</div>
                    <div><strong>Missing:</strong> {result.missing_files.join(", ") || "None"}</div>
                  </div>
                </>
              ) : (
                <div className="text-gray-500">Submit a verification to see result summary here.</div>
              )}
            </div>
          </div>

          {/* Controls */}
          <div className="bg-white p-3 rounded shadow mb-4 flex flex-col sm:flex-row gap-3 items-center">
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search name or serial..." className="flex-1 p-2 border rounded" />
            <select value={filter} onChange={(e) => setFilter(e.target.value as any)} className="p-2 border rounded">
              <option value="all">All status</option>
              <option value="complete">Complete</option>
              <option value="incomplete">Incomplete</option>
            </select>
            <select value={sortBy} onChange={(e) => setSortBy(e.target.value as any)} className="p-2 border rounded">
              <option value="name">Sort: Name</option>
              <option value="serial_no">Sort: Serial No</option>
              <option value="status">Sort: Status</option>
            </select>
          </div>

          {/* Table */}
          <div className="bg-white rounded shadow overflow-x-auto">
            <table className="min-w-full divide-y">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs text-gray-500 uppercase">Name</th>
                  <th className="px-4 py-3 text-left text-xs text-gray-500 uppercase">Serial</th>
                  <th className="px-4 py-3 text-left text-xs text-gray-500 uppercase">Status</th>
                  <th className="px-4 py-3 text-left text-xs text-gray-500 uppercase">Found</th>
                  <th className="px-4 py-3 text-left text-xs text-gray-500 uppercase">Missing</th>
                  <th className="px-4 py-3 text-left text-xs text-gray-500 uppercase">Drive</th>
                  <th className="px-4 py-3 text-center text-xs text-gray-500 uppercase">Action</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y">
                {paginated.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-6 py-8 text-center text-gray-400">No students found</td>
                  </tr>
                ) : (
                  paginated.map((s) => (
                    <tr key={s.serial_no}>
                      <td className="px-4 py-4 text-sm text-gray-800">{s.name}</td>
                      <td className="px-4 py-4 text-sm text-gray-700">{s.serial_no}</td>
                      <td className="px-4 py-4 text-sm">
                        <span className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-semibold ${s.status === "Complete" ? "bg-green-100 text-green-800" : "bg-red-100 text-red-800"}`}>{s.status}</span>
                      </td>
                      <td className="px-4 py-4 text-sm text-gray-600">{(s.found_files || []).join(", ") || "—"}</td>
                      <td className="px-4 py-4 text-sm text-gray-600">{(s.missing_files || []).join(", ") || "—"}</td>
                      <td className="px-4 py-4 text-sm">{s.drive_link ? <a href={s.drive_link} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">View</a> : <span className="text-gray-400">None</span>}</td>
                      <td className="px-4 py-4 text-center space-x-2">
                        <button onClick={() => handleRefresh(s.serial_no)} className="inline-flex items-center gap-2 px-3 py-1 bg-white border rounded-md text-sm text-blue-600 hover:bg-blue-50">🔄 Refresh</button>
                        <button onClick={() => handleDelete(s.serial_no)} className="inline-flex items-center gap-2 px-3 py-1 bg-white border rounded-md text-sm text-red-600 hover:bg-red-50">🗑 Delete</button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div className="flex items-center justify-between mt-4">
            <div className="text-sm text-gray-600">Showing <strong>{paginated.length}</strong> of <strong>{filtered.length}</strong> results</div>
            <div className="flex items-center gap-2">
              <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1} className="px-3 py-1 border rounded-md bg-white hover:bg-gray-50 disabled:opacity-50">Prev</button>
              <div className="px-3 text-sm text-gray-700">Page {page} / {totalPages}</div>
              <button onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page === totalPages} className="px-3 py-1 border rounded-md bg-white hover:bg-gray-50 disabled:opacity-50">Next</button>
            </div>
          </div>
        </main>
      </div>
      <footer className="text-center text-xs text-gray-400 mt-6">© {new Date().getFullYear()} RC TRUST — Document Verification</footer>
    </div>
  );
}