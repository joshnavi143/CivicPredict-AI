import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { API_BASE_URL } from "./api";
import {
  AlertTriangle, Check, ClipboardList, Clock3, MapPin, Plus, RefreshCw,
  ShieldAlert, Users, X
} from "lucide-react";
import "./OperationsCenter.css";

const API = API_BASE_URL;
const STAFF_ROLES = ["administrator", "department_official", "field_worker"];
const ADMIN_ROLE = "administrator";
const ISSUE_CATEGORIES = ["water", "waste", "drainage", "other"];
const PRIORITIES = ["low", "medium", "high", "critical"];
const STATUSES = ["open", "acknowledged", "in_progress", "verification_required", "resolved", "closed"];

const errorMessage = (error) =>
  error.response?.data?.detail || error.message || "The operation could not be completed.";

const toLocalDateTime = (value) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
};

function OperationsCenter({ user, predictions = [] }) {
  const isAdmin = user.role === ADMIN_ROLE;
  const isStaff = STAFF_ROLES.includes(user.role);
  const [activeTab, setActiveTab] = useState(user.role === "citizen" ? "complaints" : "overview");
  const [areas, setAreas] = useState([]);
  const [departments, setDepartments] = useState([]);
  const [summary, setSummary] = useState(null);
  const [incidents, setIncidents] = useState([]);
  const [complaints, setComplaints] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [escalations, setEscalations] = useState([]);
  const [users, setUsers] = useState([]);
  const [assignableUsers, setAssignableUsers] = useState([]);
  const [feedback, setFeedback] = useState([]);
  const [feedbackMetrics, setFeedbackMetrics] = useState(null);
  const [weather, setWeather] = useState(null);
  const [settings, setSettings] = useState(null);
  const [selectedIncident, setSelectedIncident] = useState(null);
  const [filters, setFilters] = useState({
    area_id: "", department_id: "", issue_category: "", priority: "", status: "",
    date_from: "", date_to: ""
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [acknowledgement, setAcknowledgement] = useState(null);
  const [complaintForm, setComplaintForm] = useState({
    area_id: "", issue_category: "water", description: "", reporter_name: "",
    reporter_contact: "", priority: "medium"
  });
  const [complaintRegistrationMode, setComplaintRegistrationMode] = useState("municipal_staff");
  const [areaForm, setAreaForm] = useState({ area_name: "", ward_code: "" });
  const [areaEdit, setAreaEdit] = useState(null);
  const [areaObservationTarget, setAreaObservationTarget] = useState("");
  const [areaObservationForm, setAreaObservationForm] = useState({
    source: "Municipal field observation",
    observed_at: new Date().toISOString(),
    rainfall_mm: 0,
    temperature_c: 25,
    humidity_pct: 60,
    water_supply_hours: 8,
    water_pressure: 50,
    missed_pickups: 0,
    collection_frequency_per_week: 3,
    complaints_count: 0,
    pipeline_age_years: 10,
    drainage_capacity_pct: 75,
    previous_repairs_6m: 0
  });
  const [departmentForm, setDepartmentForm] = useState({ department_id: "", name: "", category: "" });
  const [userForm, setUserForm] = useState({
    username: "", display_name: "", password: "", role: "field_worker", department_id: ""
  });
  const [feedbackForm, setFeedbackForm] = useState({
    prediction_id: "", incident_id: "", outcome: "unknown", feedback_notes: ""
  });
  const [weatherForm, setWeatherForm] = useState({
    area_id: "", source: "Municipal field observation", observed_at: "",
    rainfall_mm: "", temperature_c: "", humidity_pct: "", notes: ""
  });
  const [taskDetails, setTaskDetails] = useState({});
  const [verificationNotes, setVerificationNotes] = useState({});
  const [assignments, setAssignments] = useState({});
  const [supportingDepartmentIds, setSupportingDepartmentIds] = useState([]);

  const request = useCallback(async (path, params) => {
    const response = await axios.get(`${API}${path}`, { params });
    return response.data;
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    const jobs = [
      ["areas", () => request("/areas")],
      ["departments", () => request("/departments")],
      ["complaints", () => request("/complaints")]
    ];
    if (isStaff) {
      jobs.push(
        ["summary", () => request("/incidents/summary")],
        ["incidents", () => request("/incidents", {
          ...Object.fromEntries(Object.entries(filters).filter(([, value]) => value)),
          date_to: filters.date_to ? `${filters.date_to}T23:59:59Z` : undefined
        })],
        ["tasks", () => request("/tasks")],
        ["alerts", () => request("/alerts")],
        ["escalations", () => request("/escalations")],
        ["assignableUsers", () => request("/users/assignable")],
        ["weather", () => request("/weather/status")]
      );
    }
    if (isAdmin) jobs.push(["users", () => request("/users")], ["settings", () => request("/system/settings")]);
    if (user.role === "administrator" || user.role === "department_official") {
      jobs.push(
        ["feedback", () => request("/prediction-feedback")],
        ["feedbackMetrics", () => request("/prediction-feedback/metrics")]
      );
    }

    const results = await Promise.allSettled(jobs.map(([, load]) => load()));
    const failures = [];
    results.forEach((result, index) => {
      if (result.status === "rejected") {
        failures.push(errorMessage(result.reason));
        return;
      }
      const [key] = jobs[index];
      const data = result.value;
      if (key === "areas") setAreas(data.areas);
      if (key === "departments") setDepartments(data.departments);
      if (key === "complaints") setComplaints(data.complaints);
      if (key === "summary") setSummary(data);
      if (key === "incidents") setIncidents(data.incidents);
      if (key === "tasks") setTasks(data.tasks);
      if (key === "alerts") setAlerts(data.alerts);
      if (key === "escalations") setEscalations(data.escalations);
      if (key === "users") setUsers(data.users);
      if (key === "assignableUsers") setAssignableUsers(data.users);
      if (key === "feedback") setFeedback(data.feedback);
      if (key === "feedbackMetrics") setFeedbackMetrics(data);
      if (key === "weather") setWeather(data);
      if (key === "settings") setSettings(data);
    });
    if (failures.length) setError(failures[0]);
    setLoading(false);
  }, [filters, isAdmin, isStaff, request, user.role]);

  useEffect(() => {
    let active = true;
    Promise.resolve().then(() => {
      if (active) void refresh();
    });
    return () => { active = false; };
  }, [refresh]);

  const runAction = async (action, successMessage) => {
    setError("");
    setNotice("");
    try {
      await action();
      setNotice(successMessage);
      await refresh();
    } catch (actionError) {
      setError(errorMessage(actionError));
    }
  };

  const submitComplaint = async (event) => {
    event.preventDefault();
    setError("");
    setNotice("");
    try {
      const citizenSubmission = user.role === "citizen" ||
        (user.demo_mode && complaintRegistrationMode === "citizen");
      const path = citizenSubmission ? "/complaints" : "/complaints/register-on-behalf";
      const payload = {
        ...complaintForm,
        reporter_name: citizenSubmission
          ? (complaintForm.reporter_name || user.display_name)
          : complaintForm.reporter_name
      };
      const { data } = await axios.post(`${API}${path}`, payload);
      setAcknowledgement(data);
      setNotice(`Complaint ${data.complaint_id} registered.`);
      await refresh();
    } catch (submitError) {
      setError(errorMessage(submitError));
    }
  };

  const printAcknowledgement = () => {
    if (!acknowledgement) return;
    const printWindow = window.open("", "_blank");
    if (!printWindow) {
      setError("Allow pop-ups to print the complaint acknowledgement.");
      return;
    }
    printWindow.opener = null;
    printWindow.document.body.textContent = [
      "CivicPredict AI — Complaint Acknowledgement",
      `Complaint ID: ${acknowledgement.complaint_id}`,
      `Incident ID: ${acknowledgement.incident_id}`,
      `Area: ${acknowledgement.area_name}`,
      `Registered: ${new Date(acknowledgement.submitted_at).toLocaleString()}`,
      acknowledgement.acknowledgement
    ].join("\n\n");
    printWindow.print();
  };

  const openIncident = async (incidentId) => {
    setError("");
    try {
      const data = await request(`/incidents/${incidentId}`);
      setSelectedIncident(data);
      setSupportingDepartmentIds([]);
    } catch (detailError) {
      setError(errorMessage(detailError));
    }
  };

  const updateTask = (task, status) => runAction(async () => {
    const payload = { status };
    if (status === "completed") payload.completion_details = taskDetails[task.task_id] || "";
    await axios.patch(`${API}/tasks/${task.task_id}`, payload);
  }, `Task ${task.task_id} updated.`);

  const verifyTask = (task, verified) => runAction(
    () => axios.post(`${API}/tasks/${task.task_id}/verify`, {
      verified,
      notes: verificationNotes[task.task_id] || (verified ? "Work verified." : "Work requires follow-up.")
    }),
    verified ? "Completion verified." : "Completion returned for follow-up."
  );

  const renderIncidentTable = () => (
    <div className="ops-table-wrap">
      <table className="ops-table">
        <thead><tr><th>Incident</th><th>Area / category</th><th>Priority</th><th>Status</th><th>Department</th><th>Due</th><th /></tr></thead>
        <tbody>
          {incidents.map((incident) => (
            <tr key={incident.incident_id}>
              <td><strong>{incident.incident_id.slice(0, 8)}</strong><small>{incident.complaints_count} reports</small></td>
              <td>{incident.area_name}<small>{incident.issue_category.replace("_", " ")}</small></td>
              <td><span className={`ops-badge ${incident.priority}`}>{incident.priority}</span></td>
              <td><span className={`ops-badge ${incident.status}`}>{incident.status.replaceAll("_", " ")}</span>{incident.is_escalated ? <small className="ops-escalated">Escalated</small> : null}</td>
              <td>{incident.department_name}</td>
              <td>{new Date(incident.due_at).toLocaleString()}</td>
              <td><button className="ops-button quiet" type="button" onClick={() => openIncident(incident.incident_id)}>Details</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      {!incidents.length && <div className="ops-empty">No incidents match the selected filters.</div>}
    </div>
  );

  return (
    <section className="ops-center" id="incident-management">
      <div className="ops-heading">
        <div>
          <span className="section-kicker">MUNICIPAL RESPONSE WORKSPACE</span>
          <h2>Incident &amp; Emergency Management</h2>
          <p>Coordinate reports, field actions, verification and escalation in one auditable workflow.</p>
        </div>
        <button className="ops-button quiet" type="button" onClick={refresh} disabled={loading}>
          <RefreshCw size={15} className={loading ? "ops-spin" : ""} /> Refresh
        </button>
      </div>

      {error && <div className="ops-message error" role="alert">{error}</div>}
      {notice && <div className="ops-message success" role="status">{notice}</div>}

      {isStaff && summary && (
        <div className="ops-stat-grid">
          {[
            ["Reported complaints", summary.reported_complaints, ClipboardList],
            ["Open incidents", summary.open_incidents, AlertTriangle],
            ["High priority", summary.high_priority_unresolved, ShieldAlert],
            ["Awaiting verification", summary.tasks_awaiting_verification, Check],
            ["Overdue actions", summary.overdue_actions, Clock3],
            ["Escalated", summary.escalated_incidents, AlertTriangle]
          ].map(([label, value, Icon]) => (
            <article className="ops-stat" key={label}>
              <span><Icon size={16} /></span><small>{label}</small><strong>{value}</strong>
            </article>
          ))}
        </div>
      )}

      <nav className="ops-tabs" aria-label="Operations workspace">
        {[
          ["overview", "Incidents", isStaff],
          ["complaints", "Complaint intake", true],
          ["tasks", "Field tasks", isStaff],
          ["alerts", "Alerts & escalation", isStaff],
          ["areas", "Areas & weather", isStaff],
          ["feedback", "AI feedback", user.role === "administrator" || user.role === "department_official"],
          ["admin", "Administration", isAdmin]
        ].filter(([, , visible]) => visible).map(([id, label]) => (
          <button type="button" key={id} className={activeTab === id ? "active" : ""} onClick={() => setActiveTab(id)}>{label}</button>
        ))}
      </nav>

      {activeTab === "overview" && isStaff && (
        <div className="ops-section">
          <div className="ops-section-title"><div><h3>Incident queue</h3><p>Filter assigned and reported service incidents.</p></div></div>
          <div className="ops-filters">
            <label>Area<select value={filters.area_id} onChange={(e) => setFilters({ ...filters, area_id: e.target.value })}><option value="">All areas</option>{areas.map((area) => <option key={area.area_id} value={area.area_id}>{area.area_name}</option>)}</select></label>
            <label>Department<select value={filters.department_id} onChange={(e) => setFilters({ ...filters, department_id: e.target.value })}><option value="">All departments</option>{departments.map((dept) => <option key={dept.department_id} value={dept.department_id}>{dept.name}</option>)}</select></label>
            <label>Category<select value={filters.issue_category} onChange={(e) => setFilters({ ...filters, issue_category: e.target.value })}><option value="">All categories</option>{ISSUE_CATEGORIES.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
            <label>Priority<select value={filters.priority} onChange={(e) => setFilters({ ...filters, priority: e.target.value })}><option value="">All priorities</option>{PRIORITIES.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
            <label>Status<select value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}><option value="">All statuses</option>{STATUSES.map((item) => <option key={item} value={item}>{item.replaceAll("_", " ")}</option>)}</select></label>
            <label>From<input type="date" value={filters.date_from} onChange={(e) => setFilters({ ...filters, date_from: e.target.value })} /></label>
            <label>To<input type="date" value={filters.date_to} onChange={(e) => setFilters({ ...filters, date_to: e.target.value })} /></label>
          </div>
          {renderIncidentTable()}
          {summary?.recently_resolved?.length > 0 && (
            <div className="ops-recent"><h3>Recently resolved</h3>{summary.recently_resolved.slice(0, 5).map((item) => <span key={item.incident_id}>{item.area_name} · {item.issue_category} · {new Date(item.resolved_at).toLocaleDateString()}</span>)}</div>
          )}
          {summary?.department_assigned_incidents?.length > 0 && (
            <div className="ops-recent"><h3>Department assignments</h3>{summary.department_assigned_incidents.map((item) => <span key={item.department_id}>{item.name}: {item.assigned_incidents}</span>)}</div>
          )}
        </div>
      )}

      {activeTab === "complaints" && (
        <div className="ops-section ops-two-column">
          <div>
            <div className="ops-section-title"><div><h3>Register a service complaint</h3><p>Municipal staff can register reports for residents without smartphones.</p></div><MapPin size={18} /></div>
            <form className="ops-form" onSubmit={submitComplaint}>
              <label>Area<select required value={complaintForm.area_id} onChange={(e) => setComplaintForm({ ...complaintForm, area_id: e.target.value })}><option value="">Select verified area</option>{areas.filter((area) => area.status === "verified").map((area) => <option key={area.area_id} value={area.area_id}>{area.area_name}</option>)}</select></label>
              <label>Issue category<select value={complaintForm.issue_category} onChange={(e) => setComplaintForm({ ...complaintForm, issue_category: e.target.value })}>{ISSUE_CATEGORIES.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
              {user.demo_mode && <label>Registration channel<select value={complaintRegistrationMode} onChange={(e) => setComplaintRegistrationMode(e.target.value)}><option value="municipal_staff">Municipal staff / field worker</option><option value="citizen">Citizen self-report</option></select></label>}
              {(user.role !== "citizen" || user.demo_mode) && <label>Resident name<input required value={complaintForm.reporter_name} onChange={(e) => setComplaintForm({ ...complaintForm, reporter_name: e.target.value })} /></label>}
              <label>Contact (optional)<input value={complaintForm.reporter_contact} onChange={(e) => setComplaintForm({ ...complaintForm, reporter_contact: e.target.value })} /></label>
              <label>Priority<select value={complaintForm.priority} onChange={(e) => setComplaintForm({ ...complaintForm, priority: e.target.value })}>{PRIORITIES.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
              <label className="ops-span-two">Description<textarea required minLength={10} value={complaintForm.description} onChange={(e) => setComplaintForm({ ...complaintForm, description: e.target.value })} placeholder="Describe the service issue and when it was observed." /></label>
              <button className="ops-button primary" type="submit"><Plus size={15} /> Register complaint</button>
            </form>
            {acknowledgement && <div className="ops-ack"><strong>Complaint ID: {acknowledgement.complaint_id}</strong><span>Incident: {acknowledgement.incident_id} · Reports grouped: {acknowledgement.report_count}</span><p>{acknowledgement.acknowledgement}</p><button className="ops-button quiet" type="button" onClick={printAcknowledgement}>Print acknowledgement</button></div>}
          </div>
          <div className="ops-list-panel"><h3>Recent complaints</h3>{complaints.slice(0, 12).map((item) => <button key={item.complaint_id} type="button" className="ops-list-row" onClick={() => openIncident(item.incident_id)}><span><strong>{item.area_name} · {item.issue_category}</strong><small>{item.description}</small></span><i className={`ops-badge ${item.priority}`}>{item.incident_status}</i></button>)}{complaints.length === 0 && <div className="ops-empty">No complaints have been recorded yet.</div>}</div>
        </div>
      )}

      {activeTab === "tasks" && isStaff && (
        <div className="ops-section"><div className="ops-section-title"><div><h3>Field work &amp; verification</h3><p>Worker completion requires details and remains unverified until supervisor review.</p></div></div>
          <div className="ops-task-list">{tasks.map((task) => <article className="ops-task" key={task.task_id}><div><span className={`ops-badge ${task.status}`}>{task.status.replaceAll("_", " ")}</span><h4>{task.area_name} · {task.department_name}</h4><p>{task.task_details}</p><small>Due {new Date(task.due_at).toLocaleString()} {task.overdue ? "· OVERDUE" : ""}</small></div>
            {(task.status === "verification_required" && user.role !== "field_worker") ? <div className="ops-task-actions"><input placeholder="Verification notes" value={verificationNotes[task.task_id] || ""} onChange={(e) => setVerificationNotes({ ...verificationNotes, [task.task_id]: e.target.value })} /><button className="ops-button primary" type="button" onClick={() => verifyTask(task, true)}>Verify</button><button className="ops-button quiet" type="button" onClick={() => verifyTask(task, false)}>Return</button></div> : <div className="ops-task-actions"><input placeholder="Completion details (required)" value={taskDetails[task.task_id] || ""} onChange={(e) => setTaskDetails({ ...taskDetails, [task.task_id]: e.target.value })} /><button className="ops-button quiet" type="button" onClick={() => updateTask(task, "in_progress")}>Start</button><button className="ops-button primary" type="button" onClick={() => updateTask(task, "completed")}>Submit completion</button></div>}
          </article>)}{!tasks.length && <div className="ops-empty">No tasks are assigned to your account or department.</div>}</div>
        </div>
      )}

      {activeTab === "alerts" && isStaff && (
        <div className="ops-section ops-two-column"><div className="ops-list-panel"><h3>High-risk alerts</h3>{alerts.map((alert) => <article className="ops-alert" key={alert.alert_id}><span className={`ops-badge ${alert.severity}`}>{alert.severity}</span><div><strong>{alert.area_name} · {alert.issue_category}</strong><small>{alert.incident_status} · Due {new Date(alert.due_at).toLocaleString()}</small></div><button className="ops-button quiet" type="button" onClick={() => openIncident(alert.incident_id)}>Open</button>{alert.status === "open" && user.role !== "field_worker" && <button className="ops-button primary" type="button" onClick={() => runAction(() => axios.post(`${API}/incidents/${alert.incident_id}/acknowledge`), "Alert acknowledged.")}>Acknowledge</button>}</article>)}{!alerts.length && <div className="ops-empty">No unresolved high-risk alerts.</div>}</div>
          <div className="ops-list-panel"><h3>Escalation history</h3>{escalations.map((item) => <div className="ops-list-row" key={item.escalation_id}><span><strong>Level {item.level} · {item.area_name}</strong><small>{item.reason}</small></span><small>{new Date(item.escalated_at).toLocaleString()}</small></div>)}{!escalations.length && <div className="ops-empty">No incidents have escalated.</div>}<h3 className="ops-subheading">Internal notification delivery</h3><p className="ops-disclaimer">Notifications are recorded in the internal queue only. No SMS, email or messaging provider is configured.</p></div>
        </div>
      )}

      {activeTab === "areas" && isStaff && (
        <div className="ops-section ops-two-column">                <div className="ops-list-panel"><div className="ops-section-title"><div><h3>Registered areas</h3><p>Pending areas cannot receive complaints or predictions.</p></div></div>{areas.map((area) => <div className="ops-area-row" key={area.area_id}><div><strong>{area.area_name}</strong><small>{area.ward_code || "No ward code"} · {area.valid_data_points} recorded observations</small></div><span className={`ops-badge ${area.status}`}>{area.status}</span>{isAdmin && <>{area.status !== "verified" && <button className="ops-button quiet" type="button" onClick={() => setAreaObservationTarget(area.area_id)}>Record data</button>}{area.status !== "verified" && <button className="ops-button primary" type="button" disabled={area.valid_data_points < 3} onClick={() => { if (window.confirm("Confirm that the recorded observations are valid and this area is model-ready?")) runAction(() => axios.put(`${API}/areas/${area.area_id}/verification`, { verified: true, model_ready: true }), "Area verified and enabled for predictions."); }}>Verify</button>}<button className="ops-button quiet" type="button" onClick={() => setAreaEdit({ area_id: area.area_id, area_name: area.area_name, ward_code: area.ward_code || "", reason: "" })}>Correct</button></>}</div>)}{isAdmin && areaObservationTarget && <form className="ops-form compact" onSubmit={(e) => { e.preventDefault(); const payload = { ...areaObservationForm, observed_at: areaObservationForm.observed_at, rainfall_mm: Number(areaObservationForm.rainfall_mm), temperature_c: Number(areaObservationForm.temperature_c), humidity_pct: Number(areaObservationForm.humidity_pct), water_supply_hours: Number(areaObservationForm.water_supply_hours), water_pressure: Number(areaObservationForm.water_pressure), missed_pickups: Number(areaObservationForm.missed_pickups), collection_frequency_per_week: Number(areaObservationForm.collection_frequency_per_week), complaints_count: Number(areaObservationForm.complaints_count), pipeline_age_years: Number(areaObservationForm.pipeline_age_years), drainage_capacity_pct: Number(areaObservationForm.drainage_capacity_pct), previous_repairs_6m: Number(areaObservationForm.previous_repairs_6m) }; runAction(() => axios.post(`${API}/areas/${areaObservationTarget}/observations`, payload), "Area observation recorded. Three valid observations are required before verification."); }}><h4>Record model data observation</h4><p>Use documented municipal observations; each saved record is attributed to the administrator.</p><label>Source<input required value={areaObservationForm.source} onChange={(e) => setAreaObservationForm({ ...areaObservationForm, source: e.target.value })} /></label><label>Observed at<input required type="datetime-local" value={toLocalDateTime(areaObservationForm.observed_at)} onChange={(e) => setAreaObservationForm({ ...areaObservationForm, observed_at: e.target.value ? new Date(e.target.value).toISOString() : "" })} /></label>{Object.keys(areaObservationForm).filter((key) => !["source", "observed_at"].includes(key)).map((key) => <label key={key}>{key.replaceAll("_", " ")}<input required type="number" step="any" value={areaObservationForm[key]} onChange={(e) => setAreaObservationForm({ ...areaObservationForm, [key]: e.target.value })} /></label>)}<button className="ops-button primary">Save observation</button><button className="ops-button quiet" type="button" onClick={() => setAreaObservationTarget("")}>Cancel</button></form>}{areaEdit && <form className="ops-form compact" onSubmit={(e) => { e.preventDefault(); runAction(() => axios.put(`${API}/areas/${areaEdit.area_id}`, areaEdit), "Area correction saved and audited."); setAreaEdit(null); }}><h4>Correct area assignment</h4><label>Area name<input required value={areaEdit.area_name} onChange={(e) => setAreaEdit({ ...areaEdit, area_name: e.target.value })} /></label><label>Ward code<input value={areaEdit.ward_code} onChange={(e) => setAreaEdit({ ...areaEdit, ward_code: e.target.value })} /></label><label>Reason<input required minLength={5} value={areaEdit.reason} onChange={(e) => setAreaEdit({ ...areaEdit, reason: e.target.value })} /></label><button className="ops-button primary">Save correction</button></form>}</div>
          <div className="ops-list-panel"><h3>Weather data reliability</h3><span className={`ops-badge ${weather?.is_stale ? "high" : "low"}`}>{weather?.provider_status || "checking"}</span><p>{weather?.warning || "Loading source status..."}</p>{weather?.latest_observation && <p>Latest record: {weather.latest_observation.area_name} · {weather.latest_observation.source} · {new Date(weather.latest_observation.observed_at).toLocaleString()}</p>}<p className="ops-disclaimer">{weather?.fallback}</p>{isAdmin && <form className="ops-form compact" onSubmit={(e) => { e.preventDefault(); runAction(() => axios.post(`${API}/weather/observations`, { ...weatherForm, observed_at: weatherForm.observed_at, rainfall_mm: weatherForm.rainfall_mm === "" ? null : Number(weatherForm.rainfall_mm), temperature_c: weatherForm.temperature_c === "" ? null : Number(weatherForm.temperature_c), humidity_pct: weatherForm.humidity_pct === "" ? null : Number(weatherForm.humidity_pct) }), "Manual weather observation recorded."); }}><h4>Record manual observation</h4><label>Area<select required value={weatherForm.area_id} onChange={(e) => setWeatherForm({ ...weatherForm, area_id: e.target.value })}><option value="">Select area</option>{areas.map((area) => <option key={area.area_id} value={area.area_id}>{area.area_name}</option>)}</select></label><label>Source<input required value={weatherForm.source} onChange={(e) => setWeatherForm({ ...weatherForm, source: e.target.value })} /></label><label>Observed at<input required type="datetime-local" value={weatherForm.observed_at} onChange={(e) => setWeatherForm({ ...weatherForm, observed_at: e.target.value ? new Date(e.target.value).toISOString() : "" })} /></label><label>Rainfall (mm)<input type="number" min="0" value={weatherForm.rainfall_mm} onChange={(e) => setWeatherForm({ ...weatherForm, rainfall_mm: e.target.value })} /></label><label>Temperature (°C)<input type="number" value={weatherForm.temperature_c} onChange={(e) => setWeatherForm({ ...weatherForm, temperature_c: e.target.value })} /></label><label>Humidity (%)<input type="number" min="0" max="100" value={weatherForm.humidity_pct} onChange={(e) => setWeatherForm({ ...weatherForm, humidity_pct: e.target.value })} /></label><button className="ops-button primary">Save observation</button></form>}</div>
        </div>
      )}

      {activeTab === "feedback" && (user.role === "administrator" || user.role === "department_official") && (
        <div className="ops-section ops-two-column"><form className="ops-form" onSubmit={(e) => { e.preventDefault(); runAction(() => axios.post(`${API}/prediction-feedback`, { ...feedbackForm, prediction_id: Number(feedbackForm.prediction_id), incident_id: feedbackForm.incident_id || null }), "Prediction outcome recorded for model evaluation."); }}><h3>Record verified model outcome</h3><p>Risk classes are early warnings, not guarantees. Only use confirmed outcome information.</p><label>Prediction<select required value={feedbackForm.prediction_id} onChange={(e) => setFeedbackForm({ ...feedbackForm, prediction_id: e.target.value })}><option value="">Select prediction</option>{predictions.map((item) => <option key={item.prediction_id} value={item.prediction_id}>#{item.prediction_id} · {item.area || item.ward_name} · {new Date(item.prediction_datetime).toLocaleString()}</option>)}</select></label><label>Outcome<select value={feedbackForm.outcome} onChange={(e) => setFeedbackForm({ ...feedbackForm, outcome: e.target.value })}><option value="unknown">Unknown / not verified</option><option value="failure">Failure occurred</option><option value="no_failure">No failure observed</option></select></label><label>Incident ID (optional)<input value={feedbackForm.incident_id} onChange={(e) => setFeedbackForm({ ...feedbackForm, incident_id: e.target.value })} /></label><label>Evidence / notes<textarea required minLength={5} value={feedbackForm.feedback_notes} onChange={(e) => setFeedbackForm({ ...feedbackForm, feedback_notes: e.target.value })} /></label><button className="ops-button primary">Submit verified feedback</button></form><div className="ops-list-panel"><h3>Verified outcome monitor</h3>{feedbackMetrics && <div className="ops-feedback-grid">{[["True positive", feedbackMetrics.true_positive], ["False positive", feedbackMetrics.false_positive], ["True negative", feedbackMetrics.true_negative], ["False negative", feedbackMetrics.false_negative]].map(([label, count]) => <div key={label}><small>{label}</small><strong>{count}</strong></div>)}</div>}<p className="ops-disclaimer">{feedbackMetrics?.definition}</p><h3>Model feedback history</h3>{feedback.map((item) => <div className="ops-list-row" key={item.feedback_id}><span><strong>Prediction #{item.prediction_id} · {item.ward_name}</strong><small>{item.outcome} · {item.feedback_notes}</small></span><small>{new Date(item.submitted_at).toLocaleDateString()}</small></div>)}{!feedback.length && <div className="ops-empty">No outcomes have been recorded.</div>}</div></div>
      )}

      {activeTab === "admin" && isAdmin && (
        <div className="ops-section ops-admin-grid">
          <form className="ops-form" onSubmit={(e) => { e.preventDefault(); runAction(() => axios.post(`${API}/areas`, areaForm), "Area registered in pending verification."); setAreaForm({ area_name: "", ward_code: "" }); }}><h3><MapPin size={16} /> Register new area</h3><p>New areas remain pending; prediction requires explicit verification and data readiness.</p><label>Area name<input required minLength={2} value={areaForm.area_name} onChange={(e) => setAreaForm({ ...areaForm, area_name: e.target.value })} /></label><label>Ward code<input value={areaForm.ward_code} onChange={(e) => setAreaForm({ ...areaForm, ward_code: e.target.value })} /></label><button className="ops-button primary">Register pending area</button></form>
          <form className="ops-form" onSubmit={(e) => { e.preventDefault(); runAction(() => axios.post(`${API}/departments`, departmentForm), "Department created."); setDepartmentForm({ department_id: "", name: "", category: "" }); }}><h3><Users size={16} /> Register department</h3><label>Department ID<input required pattern="[a-z0-9_-]+" value={departmentForm.department_id} onChange={(e) => setDepartmentForm({ ...departmentForm, department_id: e.target.value })} /></label><label>Name<input required value={departmentForm.name} onChange={(e) => setDepartmentForm({ ...departmentForm, name: e.target.value })} /></label><label>Category<input required value={departmentForm.category} onChange={(e) => setDepartmentForm({ ...departmentForm, category: e.target.value })} placeholder="e.g. roads" /></label><button className="ops-button primary">Create department</button></form>
          <form className="ops-form" onSubmit={(e) => { e.preventDefault(); runAction(() => axios.post(`${API}/users`, userForm), "Account created."); setUserForm({ username: "", display_name: "", password: "", role: "field_worker", department_id: "" }); }}><h3><Users size={16} /> Create staff account</h3><label>Username<input required minLength={3} value={userForm.username} onChange={(e) => setUserForm({ ...userForm, username: e.target.value })} /></label><label>Display name<input required value={userForm.display_name} onChange={(e) => setUserForm({ ...userForm, display_name: e.target.value })} /></label><label>Temporary password<input required minLength={12} type="password" value={userForm.password} onChange={(e) => setUserForm({ ...userForm, password: e.target.value })} /></label><label>Role<select value={userForm.role} onChange={(e) => setUserForm({ ...userForm, role: e.target.value })}><option value="department_official">Department official</option><option value="field_worker">Field worker</option><option value="citizen">Citizen</option><option value="administrator">Administrator</option></select></label><label>Department<select value={userForm.department_id} onChange={(e) => setUserForm({ ...userForm, department_id: e.target.value })}><option value="">None</option>{departments.map((dept) => <option key={dept.department_id} value={dept.department_id}>{dept.name}</option>)}</select></label><button className="ops-button primary">Create account</button></form>
          <form className="ops-form" onSubmit={(e) => { e.preventDefault(); const payload = { ...settings, working_days: settings.working_days.split(",").map(Number), weather_max_age_hours: Number(settings.weather_max_age_hours), routine_acknowledgement_hours: Number(settings.routine_acknowledgement_hours), escalation_level_1_minutes: Number(settings.escalation_level_1_minutes), escalation_level_2_minutes: Number(settings.escalation_level_2_minutes), escalation_level_3_minutes: Number(settings.escalation_level_3_minutes) }; runAction(() => axios.put(`${API}/system/settings`, payload), "Notification and escalation settings saved."); }}><h3>System schedule &amp; safeguards</h3><p>Critical emergency notifications bypass routine working hours. No external delivery provider is connected.</p>{settings && <><label>Working hours start<input required type="time" value={settings.working_hours_start} onChange={(e) => setSettings({ ...settings, working_hours_start: e.target.value })} /></label><label>Working hours end<input required type="time" value={settings.working_hours_end} onChange={(e) => setSettings({ ...settings, working_hours_end: e.target.value })} /></label><label>Working days (0 Mon – 6 Sun)<input required value={settings.working_days} onChange={(e) => setSettings({ ...settings, working_days: e.target.value })} /></label><label>Max weather age (hours)<input required type="number" min="1" max="168" value={settings.weather_max_age_hours} onChange={(e) => setSettings({ ...settings, weather_max_age_hours: e.target.value })} /></label><label>Routine acknowledgement (hours)<input required type="number" min="1" max="168" value={settings.routine_acknowledgement_hours} onChange={(e) => setSettings({ ...settings, routine_acknowledgement_hours: e.target.value })} /></label>{[1, 2, 3].map((level) => <label key={level}>Escalation level {level} (minutes)<input required type="number" min="1" max="10080" value={settings[`escalation_level_${level}_minutes`]} onChange={(e) => setSettings({ ...settings, [`escalation_level_${level}_minutes`]: e.target.value })} /></label>)}<button className="ops-button primary">Save system settings</button></>}{users.length > 0 && <p><strong>{users.length}</strong> registered accounts</p>}</form>
        </div>
      )}

      {selectedIncident && (
        <div className="ops-modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) setSelectedIncident(null); }}>
          <section className="ops-modal" role="dialog" aria-modal="true" aria-labelledby="ops-incident-title">
            <button type="button" className="ops-modal-close" onClick={() => setSelectedIncident(null)} aria-label="Close incident"><X size={17} /></button>
            <span className="section-kicker">INCIDENT RECORD</span><h2 id="ops-incident-title">{selectedIncident.area_name} · {selectedIncident.issue_category}</h2><p>{selectedIncident.incident_id}</p>
            <div className="ops-detail-grid"><div><small>Priority / status</small><strong>{selectedIncident.priority} · {selectedIncident.status.replaceAll("_", " ")}</strong></div><div><small>Primary department</small><strong>{selectedIncident.department_name}</strong></div><div><small>Responsible staff</small><strong>{selectedIncident.responsible_user_name || "Not assigned"}</strong></div><div><small>Source</small><strong>{selectedIncident.complaint_source}</strong></div><div><small>Created</small><strong>{new Date(selectedIncident.created_at).toLocaleString()}</strong></div></div>
            <p>{selectedIncident.description}</p>
            {selectedIncident.ai_risk_assessment && <div className="ops-disclaimer">AI early warning only — not a confirmed service failure. {selectedIncident.ai_risk_assessment}</div>}
            {selectedIncident.resolution_details && <><h3>Resolution details</h3><p>{selectedIncident.resolution_details}</p></>}
            <h3>Departments</h3>{selectedIncident.departments?.map((dept) => <p key={dept.department_id}>{dept.name}{dept.acknowledged_at ? ` · acknowledged ${new Date(dept.acknowledged_at).toLocaleString()}` : " · awaiting acknowledgement"}</p>)}
            {(user.role === "administrator" || user.role === "department_official") && selectedIncident.status !== "resolved" && selectedIncident.status !== "closed" && <form className="ops-form compact" onSubmit={(e) => { e.preventDefault(); const assignment = assignments[selectedIncident.incident_id] || {}; runAction(() => axios.post(`${API}/incidents/${selectedIncident.incident_id}/assign`, { department_id: assignment.department_id || selectedIncident.primary_department_id, responsible_user_id: assignment.responsible_user_id ? Number(assignment.responsible_user_id) : null, task_details: assignment.task_details || "Investigate and respond to the reported service issue.", due_at: assignment.due_at ? new Date(assignment.due_at).toISOString() : null }), "Action task assigned."); }}><h4>Assign action task</h4><label>Department<select value={(assignments[selectedIncident.incident_id]?.department_id) || selectedIncident.primary_department_id} onChange={(e) => setAssignments({ ...assignments, [selectedIncident.incident_id]: { ...assignments[selectedIncident.incident_id], department_id: e.target.value } })}>{departments.filter((dept) => user.role === "administrator" || dept.department_id === user.department_id).map((dept) => <option key={dept.department_id} value={dept.department_id}>{dept.name}</option>)}</select></label><label>Responsible staff<select value={assignments[selectedIncident.incident_id]?.responsible_user_id || ""} onChange={(e) => setAssignments({ ...assignments, [selectedIncident.incident_id]: { ...assignments[selectedIncident.incident_id], responsible_user_id: e.target.value } })}><option value="">Unassigned</option>{assignableUsers.filter((staff) => !assignments[selectedIncident.incident_id]?.department_id || staff.department_id === assignments[selectedIncident.incident_id].department_id).map((staff) => <option key={staff.user_id} value={staff.user_id}>{staff.display_name} · {staff.role.replaceAll("_", " ")}</option>)}</select></label><label>Task details<input required minLength={5} value={assignments[selectedIncident.incident_id]?.task_details || ""} onChange={(e) => setAssignments({ ...assignments, [selectedIncident.incident_id]: { ...assignments[selectedIncident.incident_id], task_details: e.target.value } })} placeholder="Describe the required action" /></label><label>Due at<input type="datetime-local" value={assignments[selectedIncident.incident_id]?.due_at || ""} onChange={(e) => setAssignments({ ...assignments, [selectedIncident.incident_id]: { ...assignments[selectedIncident.incident_id], due_at: e.target.value } })} /></label><button className="ops-button primary">Assign task</button></form>}
            {user.role === "administrator" && selectedIncident.status !== "resolved" && selectedIncident.status !== "closed" && <div className="ops-form compact"><h4>Add supporting departments</h4><label>Departments<select multiple value={supportingDepartmentIds} onChange={(e) => setSupportingDepartmentIds(Array.from(e.target.selectedOptions, (option) => option.value))}>{departments.filter((dept) => !selectedIncident.departments?.some((assigned) => assigned.department_id === dept.department_id)).map((dept) => <option key={dept.department_id} value={dept.department_id}>{dept.name}</option>)}</select></label><button className="ops-button quiet" type="button" disabled={!supportingDepartmentIds.length} onClick={() => runAction(() => axios.post(`${API}/incidents/${selectedIncident.incident_id}/departments`, { department_ids: supportingDepartmentIds }), "Supporting departments added.")}>Add departments</button></div>}
            <h3>Action / completion history</h3>{selectedIncident.action_history?.map((item) => <p key={item.completion_id}>{item.submitter_name} · {item.completion_status} · {item.completion_details} {item.verification_notes ? `· ${item.verification_notes}` : ""}</p>)}{!selectedIncident.action_history?.length && <p>No completion updates recorded.</p>}
            <h3>Escalation history</h3>{selectedIncident.escalation_history?.map((item) => <p key={item.escalation_id}>Level {item.level} · {item.recipient_role} · {new Date(item.escalated_at).toLocaleString()}</p>)}{!selectedIncident.escalation_history?.length && <p>No escalations recorded.</p>}
            <h3>Complaints ({selectedIncident.report_count})</h3>{selectedIncident.complaints?.map((item) => <p key={item.complaint_id}>{item.reporter_name} · {new Date(item.submitted_at).toLocaleString()} · {item.description}</p>)}
            {isStaff && selectedIncident.status !== "resolved" && selectedIncident.status !== "closed" && <div className="ops-modal-actions"><button type="button" className="ops-button quiet" onClick={() => runAction(() => axios.post(`${API}/incidents/${selectedIncident.incident_id}/acknowledge`), "Incident acknowledged.")}>Acknowledge</button><button type="button" className="ops-button primary" onClick={() => { const resolution = window.prompt("Enter resolution details (minimum 10 characters):"); if (resolution && resolution.trim().length >= 10) runAction(() => axios.post(`${API}/incidents/${selectedIncident.incident_id}/resolve`, { resolution_details: resolution }), "Incident resolved."); }}>Resolve incident</button></div>}
          </section>
        </div>
      )}
    </section>
  );
}

export default OperationsCenter;
