import ExcelJS from "exceljs";
import "leaflet/dist/leaflet.css";
import { MapContainer, TileLayer, CircleMarker, Popup } from "react-leaflet";
import { useState, useEffect } from "react";
import {
  BrowserRouter, Navigate, NavLink, Route, Routes,
  useLocation, useNavigate
} from "react-router-dom";
import axios from "axios";
import { API_BASE_URL } from "./api";
import {
  Activity, Droplets, Trash2, Waves, MapPin,
  AlertTriangle, RefreshCw, Brain, ShieldCheck, Download,
  Search, RotateCcw, LoaderCircle, Sparkles, Eye, X,
  History as HistoryIcon, CalendarClock, ShieldAlert,
  Sun, Moon, Menu, PanelLeftClose, Bell, UserRound,
  LayoutDashboard, ClipboardList, FileChartColumnIncreasing,
  ChevronRight
} from "lucide-react";
import OperationsCenter from "./OperationsCenter";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid, Cell
} from "recharts";
import "./App.css";

const authUser = {
  display_name: "Demo Operator",
  role: "administrator",
  department_id: null,
  demo_mode: true
};

const initialData = {
  ward_name: "",
  rainfall_mm: 150,
  temperature_c: 30,
  humidity_pct: 85,
  water_supply_hours: 2,
  water_pressure: 20,
  missed_pickups: 6,
  collection_frequency_per_week: 2,
  complaints_count: 25,
  pipeline_age_years: 35,
  drainage_capacity_pct: 30,
  previous_repairs_6m: 7
};
const goaCoordinates = {
  "Bicholim": [15.5937, 73.9457],
  "Calangute": [15.5439, 73.7553],
  "Canacona": [14.9959, 74.0500],
  "Candolim": [15.5181, 73.7626],
  "Curchorem": [15.2635, 74.1087],
  "Mapusa": [15.5915, 73.8080],
  "Margao": [15.2832, 73.9862],
  "Panaji": [15.4909, 73.8278],
  "Pernem": [15.7230, 73.7950],
  "Ponda": [15.4034, 74.0150],
  "Porvorim": [15.5350, 73.8310],
  "Quepem": [15.2120, 74.0770],
  "Sanguem": [15.2290, 74.1510],
  "Valpoi": [15.5320, 74.1360],
  "Vasco da Gama": [15.3980, 73.8110],
};
const SUPPORTED_AREAS = Object.keys(goaCoordinates);
const AREA_SELECTION_ERROR =
  "Select one of the 15 supported Goa areas before generating a prediction.";
const NAV_ITEMS = [
  { path: "/dashboard", title: "Dashboard", icon: LayoutDashboard },
  { path: "/ward-monitoring", title: "Ward Monitoring", icon: MapPin },
  { path: "/ai-predictions", title: "AI Predictions", icon: Brain },
  { path: "/risk-reports", title: "Risk Reports", icon: FileChartColumnIncreasing },
  { path: "/prediction-history", title: "Prediction History", icon: HistoryIcon },
  { path: "/incident-management", title: "Incident Management", icon: ClipboardList }
];

const normalizeRisk = (risk) => {
  if (typeof risk !== "string") return null;
  const normalizedRisk = risk.trim().toLowerCase();
  return ["High", "Medium", "Low"].find(
    (level) => level.toLowerCase() === normalizedRisk
  ) || null;
};

const getRiskColor = (risk, theme = "dark") => {
  const colors = theme === "light"
    ? { High: "#c6454e", Medium: "#b56a12", Low: "#19865d" }
    : { High: "#f06469", Medium: "#f3a94b", Low: "#42d392" };
  return colors[normalizeRisk(risk)] || colors.Low;
};

const getPredictionArea = (prediction) =>
  prediction.area || prediction.ward_name || "Unknown area";

const formatPredictionDateTime = (value) => {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
};

const getPredictionOverallRisk = (prediction) => {
  const risks = [
    prediction.water_supply_risk,
    prediction.waste_management_risk,
    prediction.drainage_risk
  ];

  if (risks.includes("High")) return "High";
  if (risks.includes("Medium")) return "Medium";
  return "Low";
};

function ThemeToggle({ theme, onToggle }) {
  const nextTheme = theme === "dark" ? "light" : "dark";
  const Icon = theme === "dark" ? Sun : Moon;
  return (
    <button className="icon-action theme-toggle" type="button" onClick={onToggle} aria-label={`Switch to ${nextTheme} mode`} title={`Switch to ${nextTheme} mode`}>
      <Icon size={17} />
    </button>
  );
}

function RiskBadge({ risk, children }) {
  return <span className={`risk-badge ${(risk || "").toLowerCase()}`}>{children || risk}</span>;
}

function StatCard({ label, value, note, tone = "neutral" }) {
  return (
    <article className={`report-summary-card ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {note && <small>{note}</small>}
    </article>
  );
}

function CivicPredictApp() {
  const location = useLocation();
  const navigate = useNavigate();
  const currentPage = NAV_ITEMS.find((item) => item.path === location.pathname)
    || NAV_ITEMS[0];
  const [theme, setTheme] = useState(() =>
    window.localStorage.getItem("civicpredict-theme") === "light" ? "light" : "dark"
  );
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [globalSearch, setGlobalSearch] = useState("");
  const [notificationOpen, setNotificationOpen] = useState(false);
  const [headerAlerts, setHeaderAlerts] = useState([]);
  const [alertsLoading, setAlertsLoading] = useState(true);
  const unresolvedAlerts = headerAlerts.filter(
    (alert) => !["resolved", "closed"].includes((alert.incident_status || "").toLowerCase())
  );
  const [notificationError, setNotificationError] = useState("");
  const [form, setForm] = useState(initialData);
  const [risks, setRisks] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [anomalyData, setAnomalyData] = useState(null);
  const [anomalyLoading, setAnomalyLoading] = useState(false);
  const [anomalyError, setAnomalyError] = useState("");
  const [modelMetrics, setModelMetrics] = useState(null);
  const [predictionHistory, setPredictionHistory] = useState([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState("");
  const [historySearch, setHistorySearch] = useState("All");
  const [historyRiskFilter, setHistoryRiskFilter] = useState("All");
  const [selectedPrediction, setSelectedPrediction] = useState(null);
  const [historyDetailsLoading, setHistoryDetailsLoading] = useState(false);
  const [historyDetailsError, setHistoryDetailsError] = useState("");
  const [historyActionError, setHistoryActionError] = useState("");
  const [historyDeletingId, setHistoryDeletingId] = useState(null);

  // Area monitoring states
  const [wardData, setWardData] = useState([]);
  const [wardSearch, setWardSearch] = useState("All");
  const [riskFilter, setRiskFilter] = useState("All");
  const [wardLoading, setWardLoading] = useState(true);
  const [wardError, setWardError] = useState("");

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem("civicpredict-theme", theme);
  }, [theme]);

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, [location.pathname]);

  useEffect(() => {
    axios.get(`${API_BASE_URL}/alerts`)
      .then((response) => setHeaderAlerts(response.data.alerts || []))
      .catch(() => setNotificationError("Alert feed is unavailable."))
      .finally(() => setAlertsLoading(false));
  }, []);

  // Update form fields
  const updateField = (e) => {
    const { name, value } = e.target;

    setForm({
      ...form,
      [name]: name === "ward_name" ? value : Number(value)
    });
    if (name === "ward_name") setError("");
  };

  
  // Fetch Goa area predictions
  
  // Fetch Goa area predictions
  useEffect(() => {
    const fetchWardPredictions = async () => {
      try {
        const response = await axios.get(
          `${API_BASE_URL}/ward-predictions`
        );

        setWardData(response.data.predictions);
      } catch {
        setWardError(
          "Unable to load area predictions. Please check backend."
        );
      } finally {
        setWardLoading(false);
      }
    };

    fetchWardPredictions();
  }, []);

  // Fetch model metrics
  useEffect(() => {
    const fetchModelMetrics = async () => {
      try {
        const response = await axios.get(
          `${API_BASE_URL}/model-metrics`
        );

        setModelMetrics(response.data);
      } catch {
        console.error("Unable to load model metrics.");
      }
    };

    fetchModelMetrics();
  }, []);

  // Fetch anomalies
  useEffect(() => {
    const fetchAnomalies = async () => {
      setAnomalyLoading(true);
      setAnomalyError("");

      try {
        const response = await axios.get(
          `${API_BASE_URL}/anomalies`
        );
        setAnomalyData(response.data);
      } catch {
        setAnomalyError("Unable to load anomaly detection data.");
      } finally {
        setAnomalyLoading(false);
      }
    };

    fetchAnomalies();
  }, []);

  const fetchPredictionHistory = async () => {
    setHistoryLoading(true);
    setHistoryError("");

    try {
      const response = await axios.get(
        `${API_BASE_URL}/prediction-history`
      );
      setPredictionHistory(response.data.history);
      setHistoryTotal(response.data.total_records);
    } catch (error) {
      setHistoryError(
        error.response?.data?.detail ||
        "Unable to load prediction history."
      );
    } finally {
      setHistoryLoading(false);
    }
  };

  useEffect(() => {
    const loadPredictionHistory = async () => {
      setHistoryLoading(true);
      setHistoryError("");

      try {
        const response = await axios.get(
          `${API_BASE_URL}/prediction-history`
        );
        setPredictionHistory(response.data.history);
        setHistoryTotal(response.data.total_records);
      } catch (error) {
        setHistoryError(
          error.response?.data?.detail ||
          "Unable to load prediction history."
        );
      } finally {
        setHistoryLoading(false);
      }
    };

    loadPredictionHistory();
  }, []);



  // Calculate overall area risk
  const getOverallRisk = (ward) => {
    const risks = [
      ward.water_risk,
      ward.waste_risk,
      ward.drainage_risk
    ];

    if (risks.includes("High")) return "High";
    if (risks.includes("Medium")) return "Medium";

    return "Low";
  };
  // Generate preventive recommendations

const getRecommendations = () => {
  if (!risks) return [];

  const recommendations = [];

  const getPriority = (risk) => {
    if (risk === "High") return "High";
    if (risk === "Medium") return "Medium";
    return "Low";
  };

  // WATER SUPPLY
  if (risks.water_supply_risk !== "Low") {
    const actions = [];

    if (form.water_supply_hours <= 4) {
      actions.push("Review low daily water supply hours.");
    }

    if (form.water_pressure <= 30) {
      actions.push("Inspect pipelines and check water pressure.");
    }

    if (form.pipeline_age_years >= 20) {
      actions.push("Prioritize inspection of ageing pipelines.");
    }

    if (actions.length === 0) {
      actions.push("Schedule routine water supply and pipeline inspections.");
    }

    recommendations.push({
      service: "Water Supply",
      risk: risks.water_supply_risk,
      priority: getPriority(risks.water_supply_risk),
      actions
    });
  }

  // WASTE MANAGEMENT
  if (risks.waste_management_risk !== "Low") {
    const actions = [];

    if (form.missed_pickups >= 3) {
      actions.push("Review missed waste collection pickups.");
    }

    if (form.collection_frequency_per_week <= 3) {
      actions.push("Review waste collection frequency.");
    }

    if (form.complaints_count >= 10) {
      actions.push("Investigate repeated public waste complaints.");
    }

    if (actions.length === 0) {
      actions.push("Monitor collection schedules and waste complaints.");
    }

    recommendations.push({
      service: "Waste Management",
      risk: risks.waste_management_risk,
      priority: getPriority(risks.waste_management_risk),
      actions
    });
  }

  // DRAINAGE SYSTEM
  if (risks.drainage_risk !== "Low") {
    const actions = [];

    if (form.rainfall_mm >= 100) {
      actions.push("Inspect drainage channels before heavy rainfall.");
    }

    if (form.drainage_capacity_pct <= 50) {
      actions.push("Inspect and clear drainage blockages.");
    }

    if (form.previous_repairs_6m >= 4) {
      actions.push("Review repeated drainage maintenance issues.");
    }

    if (actions.length === 0) {
      actions.push("Schedule preventive drainage inspections.");
    }

    recommendations.push({
      service: "Drainage System",
      risk: risks.drainage_risk,
      priority: getPriority(risks.drainage_risk),
      actions
    });
  }

  // HIGH PRIORITY RECOMMENDATIONS FIRST
  recommendations.sort((a, b) => {
    const priorityOrder = { High: 1, Medium: 2, Low: 3 };
    return priorityOrder[a.priority] - priorityOrder[b.priority];
  });

  return recommendations;
};



const downloadRiskReport = async () => {
  if (!risks) return;

  const recommendations = getRecommendations();

  const workbook = new ExcelJS.Workbook();
  workbook.creator = "CivicPredict AI";
  workbook.subject = "Public Service Risk Assessment";
  workbook.created = new Date();

  const sheet = workbook.addWorksheet("Risk Assessment");

  // Column widths
  sheet.columns = [
    { key: "service", width: 25 },
    { key: "risk", width: 20 },
    { key: "action", width: 65 },
  ];

  // Main title
  sheet.mergeCells("A1:C1");
  sheet.getCell("A1").value = "CIVICPREDICT AI";
  sheet.getCell("A1").font = {
    bold: true,
    size: 20,
    color: { argb: "FFFFFFFF" },
  };
  sheet.getCell("A1").alignment = {
    horizontal: "center",
    vertical: "middle",
  };
  sheet.getCell("A1").fill = {
    type: "pattern",
    pattern: "solid",
    fgColor: { argb: "FF17365D" },
  };
  sheet.getRow(1).height = 38;

  // Subtitle
  sheet.mergeCells("A2:C2");
  sheet.getCell("A2").value = "PUBLIC SERVICE RISK ASSESSMENT REPORT";
  sheet.getCell("A2").font = {
    bold: true,
    size: 12,
    color: { argb: "FF17365D" },
  };
  sheet.getCell("A2").alignment = { horizontal: "center" };
  sheet.getRow(2).height = 25;

  // Area details
  sheet.getCell("A4").value = "Area Name";
  sheet.getCell("B4").value = form.ward_name;
  sheet.getCell("A5").value = "Generated At";
  sheet.getCell("B5").value = new Date().toLocaleString();

  ["A4", "A5"].forEach((cell) => {
    sheet.getCell(cell).font = { bold: true };
    sheet.getCell(cell).fill = {
      type: "pattern",
      pattern: "solid",
      fgColor: { argb: "FFDCE6F1" },
    };
  });

  // Table heading
  const header = sheet.getRow(7);
  header.values = [
    "SERVICE",
    "PREDICTED RISK",
    "PREVENTIVE ACTIONS",
  ];
  header.height = 30;

  header.eachCell((cell) => {
    cell.font = {
      bold: true,
      color: { argb: "FFFFFFFF" },
    };
    cell.fill = {
      type: "pattern",
      pattern: "solid",
      fgColor: { argb: "FF305496" },
    };
    cell.alignment = {
      horizontal: "center",
      vertical: "middle",
    };
  });

  // Service-wise risk and actions
  const services = [
    {
      name: "Water Supply",
      risk: risks.water_supply_risk,
    },
    {
      name: "Waste Management",
      risk: risks.waste_management_risk,
    },
    {
      name: "Drainage System",
      risk: risks.drainage_risk,
    },
  ];

  services.forEach((service) => {
    const item = recommendations.find(
      (rec) => rec.service === service.name
    );

    const actions =
      item?.actions?.length > 0
        ? item.actions
        : ["No preventive action required. Continue routine monitoring."];

    actions.forEach((action) => {
      const row = sheet.addRow([
        service.name,
        service.risk,
        action,
      ]);

      row.height = 32;

      row.eachCell((cell) => {
        cell.alignment = {
          vertical: "middle",
          wrapText: true,
        };

        cell.border = {
          bottom: {
            style: "thin",
            color: { argb: "FFD9E2F3" },
          },
        };
      });

      // Risk colour
      const riskCell = row.getCell(2);

      const riskColors = {
        High: "FFFFC7CE",
        Medium: "FFFFE699",
        Low: "FFC6EFCE",
      };

      const riskTextColors = {
        High: "FF9C0006",
        Medium: "FF9C6500",
        Low: "FF006100",
      };

      riskCell.fill = {
        type: "pattern",
        pattern: "solid",
        fgColor: {
          argb: riskColors[service.risk] || "FFFFFFFF",
        },
      };

      riskCell.font = {
        bold: true,
        color: {
          argb: riskTextColors[service.risk] || "FF000000",
        },
      };

      riskCell.alignment = {
        horizontal: "center",
        vertical: "middle",
      };
    });
  });

  // Disclaimer
  const noticeRow = sheet.addRow([]);
  noticeRow.height = 12;

  const notice = sheet.addRow([
    "NOTICE",
    "Illustrative predictions based on synthetic demo data.",
  ]);

  sheet.mergeCells(`B${notice.number}:C${notice.number}`);

  notice.getCell(1).font = { bold: true };
  notice.getCell(1).fill = {
    type: "pattern",
    pattern: "solid",
    fgColor: { argb: "FFFFE699" },
  };

  notice.getCell(2).font = {
    italic: true,
    color: { argb: "FF666666" },
  };
  notice.getCell(2).alignment = { wrapText: true };

  // Freeze table heading and enable filters
  sheet.autoFilter = {
  from: "A7",
  to: `C${7 + services.reduce((count, service) => {
    const item = recommendations.find(
      (rec) => rec.service === service.name
    );
    return count + (item?.actions?.length || 1);
  }, 0)}`,
};

  // Download Excel file
  const buffer = await workbook.xlsx.writeBuffer();

  const blob = new Blob([buffer], {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });

  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");

  const safeArea = String(form.ward_name || "Area").replace(
    /[^a-z0-9_-]/gi,
    "_"
  );

  link.href = url;
  link.download = `CivicPredict_${safeArea}_Risk_Report.xlsx`;

  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);

  URL.revokeObjectURL(url);
};

  // Filter areas using search
  const filteredWards = wardData.filter((ward) => {
  const matchesSearch = wardSearch === "All" || ward.ward_name === wardSearch;

  const matchesRisk =
    riskFilter === "All" ||
    getOverallRisk(ward) === riskFilter;

  return matchesSearch && matchesRisk;
});

  // Individual area prediction
 
const predictRisk = async (e) => {
  e.preventDefault();
  setError("");
  const selectedArea = SUPPORTED_AREAS.find(
    (area) => area.toLowerCase() === String(form.ward_name || "").trim().toLowerCase()
  );
  if (!selectedArea) {
    setError(AREA_SELECTION_ERROR);
    return;
  }

  setLoading(true);

  try {
    const response = await axios.post(
      `${API_BASE_URL}/predict`,
      { ...form, ward_name: selectedArea }
    );

    setRisks(response.data);
    await fetchPredictionHistory();
    console.log("PREDICTION:", response.data);

  } catch (err) {
    console.error("Prediction error:", err.response?.data || err.message);

    setError(
      err.response?.data?.detail ||
      "Unable to connect to AI server. Check whether backend is running."
    );

  } finally {
    setLoading(false);
  }
};

const viewPredictionDetails = async (prediction) => {
  setSelectedPrediction(prediction);
  setHistoryDetailsLoading(true);
  setHistoryDetailsError("");

  try {
    const response = await axios.get(
      `${API_BASE_URL}/prediction-history/${prediction.prediction_id}`
    );
    setSelectedPrediction(response.data);
  } catch (error) {
    setHistoryDetailsError(
      error.response?.data?.detail ||
      "Unable to load prediction details."
    );
  } finally {
    setHistoryDetailsLoading(false);
  }
};

const deletePredictionHistoryItem = async (prediction) => {
  const area = getPredictionArea(prediction);
  if (!window.confirm(`Delete the prediction for ${area}? This cannot be undone.`)) {
    return;
  }

  setHistoryDeletingId(prediction.prediction_id);
  setHistoryActionError("");

  try {
    await axios.delete(
      `${API_BASE_URL}/prediction-history/${prediction.prediction_id}`
    );
    setPredictionHistory((history) =>
      history.filter(
        (item) => item.prediction_id !== prediction.prediction_id
      )
    );
    setHistoryTotal((total) => Math.max(0, total - 1));
    setSelectedPrediction((selected) =>
      selected?.prediction_id === prediction.prediction_id ? null : selected
    );
  } catch (error) {
    setHistoryActionError(
      error.response?.data?.detail ||
      "Unable to delete this prediction."
    );
  } finally {
    setHistoryDeletingId(null);
  }
};

const resetAssessment = () => {
  setForm(initialData);
  setRisks(null);
  setError("");
};



  // Risk cards
  const riskItems = risks ? [
    {
      title: "Water Supply",
      value: risks.water_supply_risk,
      icon: <Droplets />,
      color: "water"
    },
    {
      title: "Waste Management",
      value: risks.waste_management_risk,
      icon: <Trash2 />,
      color: "waste"
    },
    {
      title: "Drainage System",
      value: risks.drainage_risk,
      icon: <Waves />,
      color: "drainage"
    }
  ] : [];

  // Chart data
  const chartData = risks ? [
    {
      name: "Water",
      risk: risks.water_supply_risk
    },
    {
      name: "Waste",
      risk: risks.waste_management_risk
    },
    {
      name: "Drainage",
      risk: risks.drainage_risk
    }
  ].map((item) => {
    const risk = normalizeRisk(item.risk);
    return {
      name: item.name,
      risk,
      color: getRiskColor(risk),
      score:
        risk === "High" ? 3 :
        risk === "Medium" ? 2 :
        risk === "Low" ? 1 : 0
    };
  }) : [];

  const filteredHistory = predictionHistory
    .filter((prediction) => {
      const matchesSearch =
        historySearch === "All" ||
        getPredictionArea(prediction) === historySearch;
      const matchesRisk =
        historyRiskFilter === "All" ||
        getPredictionOverallRisk(prediction) === historyRiskFilter;

      return matchesSearch && matchesRisk;
    })
    .sort((a, b) =>
      new Date(b.prediction_datetime).getTime() -
      new Date(a.prediction_datetime).getTime()
    );

  const latestPrediction = [...predictionHistory].sort((a, b) =>
    new Date(b.prediction_datetime).getTime() -
    new Date(a.prediction_datetime).getTime()
  )[0];
  const serviceRiskDistribution = [
    { service: "Water", High: wardData.filter((ward) => ward.water_risk === "High").length, Medium: wardData.filter((ward) => ward.water_risk === "Medium").length, Low: wardData.filter((ward) => ward.water_risk === "Low").length },
    { service: "Waste", High: wardData.filter((ward) => ward.waste_risk === "High").length, Medium: wardData.filter((ward) => ward.waste_risk === "Medium").length, Low: wardData.filter((ward) => ward.waste_risk === "Low").length },
    { service: "Drainage", High: wardData.filter((ward) => ward.drainage_risk === "High").length, Medium: wardData.filter((ward) => ward.drainage_risk === "Medium").length, Low: wardData.filter((ward) => ward.drainage_risk === "Low").length }
  ];

  if (!NAV_ITEMS.some((item) => item.path === location.pathname)) {
    return <Navigate to="/dashboard" replace />;
  }

  return (
    <div className={`app theme-${theme}${sidebarCollapsed ? " sidebar-collapsed" : ""}${mobileNavOpen ? " mobile-nav-open" : ""}`}>

      {/* SIDEBAR */}
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-icon">
            <Activity />
          </div>

          <div className="brand-copy">
            <h2>CivicPredict</h2>
            <span>AI PUBLIC SERVICES</span>
          </div>
          <button
            className="sidebar-collapse"
            type="button"
            aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            onClick={() => setSidebarCollapsed((collapsed) => !collapsed)}
          >
            <PanelLeftClose size={16} />
          </button>
        </div>

        <p className="nav-label">MAIN MENU</p>
        <nav className="sidebar-nav" aria-label="Main menu">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.path}
                to={item.path}
                className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
                aria-current={currentPage.path === item.path ? "page" : undefined}
                onClick={() => setMobileNavOpen(false)}
                title={sidebarCollapsed ? item.title : undefined}
              >
                <Icon size={18} />
                <span className="nav-item-label">{item.title}</span>
                {currentPage.path === item.path && <ChevronRight className="nav-current" size={14} />}
              </NavLink>
            );
          })}
        </nav>
        <div className="sidebar-bottom">
          <ShieldCheck />

          <div className="sidebar-bottom-copy">
            <strong>Predict. Prevent. Protect.</strong>
            <span>Smarter public services</span>
          </div>
        </div>
      </aside>

      {/* MAIN DASHBOARD */}
      {mobileNavOpen && <button className="mobile-nav-backdrop" type="button" aria-label="Close navigation" onClick={() => setMobileNavOpen(false)} />}
      <main className="main" id="dashboard">

        {/* HEADER */}
        <header className="topbar">
          <div className="topbar-title">
            <button className="mobile-menu-toggle" type="button" aria-label="Open navigation" onClick={() => setMobileNavOpen(true)}>
              <Menu size={19} />
            </button>
            <div>
              <p className="topbar-breadcrumb">CIVICPREDICT <span>/</span> GOA COMMAND CENTER</p>
              <h1>{currentPage.title}</h1>
            </div>
          </div>

          <div className="topbar-actions">
            <form className="global-search" role="search" onSubmit={(event) => {
              event.preventDefault();
              const query = globalSearch.trim().toLowerCase();
              if (!query) return;
              const area = SUPPORTED_AREAS.find((name) => name.toLowerCase() === query)
                || SUPPORTED_AREAS.find((name) => name.toLowerCase().includes(query));
              const destination = NAV_ITEMS.find((item) => item.title.toLowerCase().includes(query));
              if (area) {
                setWardSearch(area);
                navigate("/ward-monitoring");
              } else if (destination) {
                navigate(destination.path);
              }
            }}>
              <Search size={16} aria-hidden="true" />
              <input aria-label="Search pages or supported areas" placeholder="Search pages or areas..." value={globalSearch} onChange={(event) => setGlobalSearch(event.target.value)} />
              <kbd>↵</kbd>
            </form>
            <ThemeToggle theme={theme} onToggle={() => setTheme((value) => value === "dark" ? "light" : "dark")} />
            <div className="notification-anchor">
              <button className="icon-action notification-toggle" type="button" aria-label={`Open alerts${unresolvedAlerts.length ? `, ${unresolvedAlerts.length} unresolved` : ""}`} onClick={() => setNotificationOpen((open) => !open)}>
                <Bell size={17} />
                {unresolvedAlerts.length > 0 && <span className="notification-count">{unresolvedAlerts.length}</span>}
              </button>
              {notificationOpen && (
                <section className="notification-panel" aria-label="Alert notifications">
                  <div className="notification-panel-heading">
                    <div><strong>Alert center</strong><small>{unresolvedAlerts.length} unresolved alerts</small></div>
                    <button className="notification-close" type="button" aria-label="Close alerts" onClick={() => setNotificationOpen(false)}><X size={15} /></button>
                  </div>
                  {notificationError ? <p className="notification-empty">{notificationError}</p> : unresolvedAlerts.length ? unresolvedAlerts.slice(0, 5).map((alert) => (
                    <button className="notification-row" type="button" key={alert.alert_id || alert.incident_id} onClick={() => { navigate("/incident-management"); setNotificationOpen(false); }}>
                      <span className={`notification-risk ${alert.severity || "medium"}`}><AlertTriangle size={14} /></span>
                      <span><strong>{alert.area_name} · {alert.issue_category}</strong><small>{alert.severity} early warning · {alert.incident_status}</small></span>
                    </button>
                  )) : <p className="notification-empty">No unresolved alerts. New operational alerts will appear here.</p>}
                  <button className="notification-footer" type="button" onClick={() => { navigate("/incident-management"); setNotificationOpen(false); }}>Open incident management <ChevronRight size={14} /></button>
                </section>
              )}
            </div>
            <span className="topbar-divider-line" />
            <div className="profile-indicator"><span className="profile-avatar"><UserRound size={15} /></span><span><strong>Demo Operator</strong><small>Administrator · Demo mode</small></span></div>
          </div>
        </header>

        {currentPage.path !== "/dashboard" && (
          <section className="page-intro">
            <span className="section-kicker">GOA PUBLIC SERVICE INTELLIGENCE</span>
            <h2>{currentPage.title}</h2>
            <p>{{
              "/ward-monitoring": "A map and area-wise view of model-generated risk indicators across Goa.",
              "/ai-predictions": "Assess service risks using the supported Goa areas and current infrastructure inputs.",
              "/risk-reports": "Review model-generated risk distributions and export the current assessment.",
              "/prediction-history": "Explore saved AI assessments, compare outcomes and review input details.",
              "/incident-management": "Coordinate reported issues, response tasks and escalation workflows."
            }[currentPage.path]}</p>
          </section>
        )}

        {/* WELCOME BANNER */}
        {currentPage.path === "/dashboard" && <>
        <section className="welcome command-hero">
          <div className="hero-copy">
            <span className="eyebrow">
              <Sparkles size={13} /> CIVICPREDICT INTELLIGENCE PLATFORM
            </span>

            <h2>See the signal.<br />Prevent the disruption.</h2>

            <p>
              Predictive oversight for Goa’s essential public services — bringing
              water, waste and drainage risks into one operational view.
            </p>

            <div className="hero-meta">
              <span><i className="hero-meta-dot" /> MODEL MONITORING</span>
              <span className="hero-meta-divider" />
              <span>GOA · INDIA</span>
            </div>
          </div>

          <div className="hero-visual" aria-hidden="true">
            <div className="hero-orbit hero-orbit-outer" />
            <div className="hero-orbit hero-orbit-inner" />
            <div className="hero-core"><Brain size={34} /></div>
            <span className="orbit-node orbit-node-one" />
            <span className="orbit-node orbit-node-two" />
            <span className="orbit-node orbit-node-three" />
            <div className="hero-signal-card">
              <span>AI MONITOR</span>
              <strong>Systems online</strong>
              <i><b /></i>
            </div>
          </div>
        </section>
        </>}

        {currentPage.path === "/incident-management" && <OperationsCenter user={authUser} predictions={predictionHistory} />}

        {currentPage.path === "/dashboard" && <>
        <section className="command-overview" aria-label="Monitoring overview">
          <article className="overview-stat overview-areas">
            <div className="overview-stat-icon"><MapPin size={18} /></div>
            <div className="overview-stat-copy">
              <span>MONITORED AREAS</span>
              <strong>{wardLoading ? "—" : wardData.length}</strong>
              <small>Goa locations</small>
            </div>
            <span className="overview-stat-index">01</span>
          </article>

          <article className="overview-stat overview-critical">
            <div className="overview-stat-icon"><AlertTriangle size={18} /></div>
            <div className="overview-stat-copy">
              <span>HIGH-RISK AREAS</span>
              <strong>{wardLoading ? "—" : wardData.filter((ward) => getOverallRisk(ward) === "High").length}</strong>
              <small>Requires attention</small>
            </div>
            <span className="overview-stat-index">02</span>
          </article>

          <article className="overview-stat overview-anomalies">
            <div className="overview-stat-icon"><Activity size={18} /></div>
            <div className="overview-stat-copy">
              <span>ANOMALIES DETECTED</span>
              <strong>{anomalyData ? anomalyData.anomaly_count : "—"}</strong>
              <small>Unusual data patterns</small>
            </div>
            <span className="overview-stat-index">03</span>
          </article>

          <article className="overview-stat overview-models">
            <div className="overview-stat-icon"><Brain size={18} /></div>
            <div className="overview-stat-copy">
              <span>ACTIVE MODELS</span>
              <strong>{modelMetrics ? "03" : "—"}</strong>
              <small>Water · Waste · Drainage</small>
            </div>
            <span className="overview-stat-index">04</span>
          </article>
        </section>

        <section className="dashboard-insights-grid" aria-label="Dashboard insights">
          <div className="panel service-snapshot-panel">
            <div className="panel-heading">
              <div><h2>Latest service outlook</h2><p>{latestPrediction ? `Most recent assessment · ${getPredictionArea(latestPrediction)}` : "Risk categories from the most recent saved assessment"}</p></div>
              <ShieldAlert size={20} />
            </div>
            <div className="service-snapshot-grid">
              {[
                ["Water Supply", latestPrediction?.water_supply_risk, Droplets],
                ["Waste Management", latestPrediction?.waste_management_risk, Trash2],
                ["Drainage", latestPrediction?.drainage_risk, Waves]
              ].map(([label, risk, Icon]) => (
                <article className={`service-snapshot-card${risk ? ` ${risk.toLowerCase()}` : ""}`} key={label}>
                  <span><Icon size={16} /></span>
                  <div><small>{label}</small><strong>{risk ? `${risk} risk` : "No assessment yet"}</strong></div>
                </article>
              ))}
            </div>
            {!latestPrediction && <p className="insight-disclaimer">Run an assessment to populate service risk indicators.</p>}
            <NavLink className="text-link" to="/ai-predictions">Open AI predictions <ChevronRight size={14} /></NavLink>
          </div>
          <div className="panel recent-activity-panel">
            <div className="panel-heading"><div><h2>Recent predictions</h2><p>Latest saved assessments</p></div><HistoryIcon size={19} /></div>
            {predictionHistory.length ? (
              <div className="recent-prediction-list">
                {predictionHistory.slice(0, 4).map((prediction) => (
                  <div className="recent-prediction-row" key={prediction.prediction_id}>
                    <span className="recent-prediction-mark"><Activity size={14} /></span>
                    <span><strong>{getPredictionArea(prediction)}</strong><small>{formatPredictionDateTime(prediction.prediction_datetime)}</small></span>
                    <RiskBadge risk={getPredictionOverallRisk(prediction)} />
                  </div>
                ))}
              </div>
            ) : <div className="compact-empty">No saved predictions yet.</div>}
            <NavLink className="text-link" to="/prediction-history">View prediction history <ChevronRight size={14} /></NavLink>
          </div>
        </section>

        <section className="dashboard-lower-grid" aria-label="Risk and alert summary">
          <div className="panel dashboard-risk-chart">
            <div className="panel-heading"><div><h2>Risk distribution by service</h2><p>Current model classifications across monitored areas</p></div><Activity size={19} /></div>
            {wardLoading ? <div className="loading-state"><span className="loading-spinner" /> Loading risk distribution...</div> : wardError ? <p className="error-message">{wardError}</p> : (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={serviceRiskDistribution}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--chart-grid)" />
                  <XAxis dataKey="service" tickLine={false} axisLine={false} tick={{ fill: "var(--chart-label)", fontSize: 10 }} />
                  <YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fill: "var(--chart-label)", fontSize: 9 }} />
                  <Tooltip contentStyle={{ color: "var(--color-text)", background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: 12 }} />
                  <Bar dataKey="High" stackId="risk" fill="var(--risk-high)" />
                  <Bar dataKey="Medium" stackId="risk" fill="var(--risk-medium)" />
                  <Bar dataKey="Low" stackId="risk" fill="var(--risk-low)" />
                </BarChart>
              </ResponsiveContainer>
            )}
            <p className="chart-note">Classifications are model-generated early warnings, not confirmed service failures.</p>
          </div>
          <div className="panel dashboard-alert-panel">
            <div className="panel-heading"><div><h2>Recent alerts</h2><p>Unresolved operational alerts</p></div><Bell size={18} /></div>
            {alertsLoading ? <div className="loading-state"><span className="loading-spinner" /> Checking alert feed...</div> : notificationError ? <p className="error-message">{notificationError}</p> : unresolvedAlerts.length ? (
              <div className="dashboard-alert-list">
                {unresolvedAlerts.slice(0, 4).map((alert) => (
                  <button className="dashboard-alert-row" type="button" key={alert.alert_id || alert.incident_id} onClick={() => navigate("/incident-management")}>
                    <span className={`notification-risk ${(alert.severity || "medium").toLowerCase()}`}><AlertTriangle size={14} /></span>
                    <span><strong>{alert.area_name} · {alert.issue_category}</strong><small>{alert.severity} priority · {alert.incident_status}</small></span>
                    <ChevronRight size={14} />
                  </button>
                ))}
              </div>
            ) : <div className="compact-empty">No unresolved alerts in the current feed.</div>}
            <NavLink className="text-link" to="/incident-management">Review incident queue <ChevronRight size={14} /></NavLink>
          </div>
        </section>

{/* AI MODEL PERFORMANCE */}
<section className="panel model-performance-panel">
  <div className="panel-heading">
    <div>
      <h2>AI Model Performance</h2>
      <p>Evaluation results across three public service prediction models</p>
    </div>
    <Brain size={25} />
  </div>

  {modelMetrics ? (
    <>
      <div className="model-metrics-grid">
        {[
          ["Water", modelMetrics.water],
          ["Waste", modelMetrics.waste],
          ["Drainage", modelMetrics.drainage]
        ].map(([name, metrics]) => (
          <div className="model-metric-card" key={name}>
            <h3>{name} Model</h3>

            <div className="model-accuracy">
              {(metrics.accuracy * 100).toFixed(1)}%
            </div>

            <p>Accuracy</p>
            <div
              className="accuracy-track"
              role="img"
              aria-label={`${name} model accuracy ${(metrics.accuracy * 100).toFixed(1)} percent`}
            >
              <span style={{ width: `${metrics.accuracy * 100}%` }} />
            </div>

            <div className="metric-row">
              <span>Precision</span>
              <strong>{(metrics.precision * 100).toFixed(2)}%</strong>
            </div>

            <div className="metric-row">
              <span>Recall</span>
              <strong>{(metrics.recall * 100).toFixed(2)}%</strong>
            </div>

            <div className="metric-row">
              <span>F1 Score</span>
              <strong>{(metrics.f1_score * 100).toFixed(2)}%</strong>
            </div>
          </div>
        ))}
      </div>

      <p className="chart-note">
        Metrics are weighted averages calculated on a held-out
        synthetic demo test set of 100 records per model.
        They do not represent verified real-world performance.
      </p>
    </>
  ) : (
    <div className="loading-state"><span className="loading-spinner" /> Loading model performance...</div>
  )}
</section>

        {/* AI ANOMALY DETECTION */}
<section className="panel anomaly-panel">
  <div className="panel-heading">
    <div>
      <h2>AI Anomaly Detection</h2>
      <p>Unusual public service patterns identified using Isolation Forest</p>
    </div>
    <Brain size={25} />
  </div>

  {anomalyLoading ? (
    <div className="loading-state"><span className="loading-spinner" /> Analysing unusual patterns...</div>
  ) : anomalyError ? (
    <p className="error-message">{anomalyError}</p>
  ) : anomalyData ? (
    <>
      <div className="stats-grid anomaly-stats-grid">
        <div className="stat-card total-stat">
          <div className="stat-card-icon"><Activity size={17} /></div>
          <h3>Total Records</h3>
          <h2>{anomalyData.total_records}</h2>
          <span className="stat-card-foot">Records analysed</span>
        </div>

        <div className="stat-card normal-stat">
          <div className="stat-card-icon"><ShieldCheck size={17} /></div>
          <h3>Normal Records</h3>
          <h2>{anomalyData.normal_records}</h2>
          <span className="stat-card-foot">Within expected patterns</span>
        </div>

        <div className="stat-card anomaly-stat">
          <div className="stat-card-icon"><AlertTriangle size={17} /></div>
          <h3>Anomalies Detected</h3>
          <h2>{anomalyData.anomaly_count}</h2>
          <span className="stat-card-foot">Unusual patterns flagged</span>
        </div>
      </div>

      <h3>Detected Unusual Patterns</h3>

      <div className="table-container anomaly-table-container">
        <table>
          <thead>
            <tr>
              <th>Area</th>
              <th>Date</th>
              <th>Status</th>
              <th>Anomaly Score</th>
            </tr>
          </thead>

          <tbody>
            {anomalyData.anomalies.map((item, index) => (
              <tr key={`${item.ward_name}-${item.date}-${index}`}>
                <td>{item.ward_name}</td>
                <td>{item.date}</td>
                <td>
                  <span className="risk-badge high">
                    {item.anomaly_status}
                  </span>
                </td>
                <td>{Number(item.anomaly_score).toFixed(5)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="chart-note">
        Anomalies indicate unusual data patterns, not confirmed service failures.
        Dataset source: Synthetic demo data.
      </p>
    </>
  ) : null}
</section>
        </>}

        {/* RISK OVERVIEW */}
        {currentPage.path === "/ai-predictions" && <>
        <section className="section-heading">
          <div>
            <span className="section-kicker">SELECTED AREA · {form.ward_name || "GOA"}</span>
            <h2>Service Risk Overview</h2>
            <p>
              AI prediction results for the selected area
            </p>
          </div>

          <button
            className="refresh"
            onClick={() => setRisks(null)}
          >
            <RefreshCw size={16} />
            Clear results
          </button>
        </section>

        {/* RISK CARDS */}
        <section className="risk-grid">
          {riskItems.length > 0 ? (
            riskItems.map((item) => {
              const risk = normalizeRisk(item.value);
              const riskClass = risk ? risk.toLowerCase() : "unknown";
              return (
                <div
                  className="risk-card"
                  key={item.title}
                >
                  <div className={`risk-icon ${item.color} risk-${riskClass}`}>
                    {item.icon}
                  </div>

                  <p>{item.title}</p>

                  <h2 className={riskClass}>
                    {risk ? `${risk} Risk` : "Risk unavailable"}
                  </h2>

                  <span>AI model prediction</span>
                </div>
              );
            })
          ) : (
            <div className="empty-state">
              <Brain size={30} />

              <h3>Awaiting AI prediction</h3>

              <p>
                Enter area information below and run the prediction.
              </p>
            </div>
          )}
        </section>

        {/* INPUT FORM AND CHART */}
        <section className="content-grid" id="ai-predictions">

          {/* INPUT FORM */}
          <div className={`panel input-panel ${loading ? "is-scanning" : ""}`}>
            <div className="panel-heading">
              <div>
                <h2>Area Risk Assessment</h2>
                <p>
                  Enter infrastructure and service information
                </p>
              </div>

              <MapPin />
            </div>

            <form onSubmit={predictRisk} noValidate>

            

             
              <div className="form-area-field">
                <label htmlFor="ward_name">Ward / Area Name</label>
                <select
                  id="ward_name"
                  name="ward_name"
                  value={form.ward_name}
                  onChange={updateField}
                  aria-invalid={Boolean(error)}
                  aria-describedby={error ? "area-selection-error" : undefined}
                  required
                >
                  <option value="">Select a supported Goa area</option>
                  {SUPPORTED_AREAS.map((area) => (
                    <option key={area} value={area}>{area}</option>
                  ))}
                </select>
              </div>

              <div className="form-groups">
                <fieldset className="input-group climate-group">
                  <legend><Activity size={15} /> Climate signals</legend>
                  <div className="form-grid">
                    {[
                      ["rainfall_mm", "Rainfall (mm)"],
                      ["temperature_c", "Temperature (°C)"],
                      ["humidity_pct", "Humidity (%)"]
                    ].map(([name, label]) => (
                      <div key={name}>
                        <label htmlFor={name}>{label}</label>
                        <input
                          id={name}
                          type="number"
                          name={name}
                          value={form[name]}
                          onChange={updateField}
                          placeholder={`Enter ${label.toLowerCase()}`}
                          min="0"
                          step="any"
                          required
                        />
                      </div>
                    ))}
                  </div>
                </fieldset>

                <fieldset className="input-group water-group">
                  <legend><Droplets size={15} /> Water supply</legend>
                  <div className="form-grid">
                    {[
                      ["water_supply_hours", "Water supply hours"],
                      ["water_pressure", "Water pressure"],
                      ["pipeline_age_years", "Pipeline age (years)"]
                    ].map(([name, label]) => (
                      <div key={name}>
                        <label htmlFor={name}>{label}</label>
                        <input
                          id={name}
                          type="number"
                          name={name}
                          value={form[name]}
                          onChange={updateField}
                          placeholder={`Enter ${label.toLowerCase()}`}
                          min="0"
                          step="any"
                          required
                        />
                      </div>
                    ))}
                  </div>
                </fieldset>

                <fieldset className="input-group waste-group">
                  <legend><Trash2 size={15} /> Waste management</legend>
                  <div className="form-grid">
                    {[
                      ["missed_pickups", "Missed waste pickups"],
                      ["collection_frequency_per_week", "Collection frequency / week"],
                      ["complaints_count", "Complaints count"]
                    ].map(([name, label]) => (
                      <div key={name}>
                        <label htmlFor={name}>{label}</label>
                        <input
                          id={name}
                          type="number"
                          name={name}
                          value={form[name]}
                          onChange={updateField}
                          placeholder={`Enter ${label.toLowerCase()}`}
                          min="0"
                          step="any"
                          required
                        />
                      </div>
                    ))}
                  </div>
                </fieldset>

                <fieldset className="input-group drainage-group">
                  <legend><Waves size={15} /> Drainage system</legend>
                  <div className="form-grid">
                    {[
                      ["drainage_capacity_pct", "Drainage capacity (%)"],
                      ["previous_repairs_6m", "Repairs in last 6 months"]
                    ].map(([name, label]) => (
                      <div key={name}>
                        <label htmlFor={name}>{label}</label>
                        <input
                          id={name}
                          type="number"
                          name={name}
                          value={form[name]}
                          onChange={updateField}
                          placeholder={`Enter ${label.toLowerCase()}`}
                          min="0"
                          step="any"
                          required
                        />
                      </div>
                    ))}
                  </div>
                </fieldset>
              </div>

              <div className="form-actions">
                <button
                  className={`predict-button ${loading ? "is-loading" : ""}`}
                  type="submit"
                  disabled={loading}
                >
                  {loading
                    ? <LoaderCircle size={18} className="spin" />
                    : <Brain size={18} />}
                  {loading ? "AI scan in progress..." : "Generate AI Prediction"}
                </button>
                <button
                  className="reset-form-button"
                  type="button"
                  onClick={resetAssessment}
                  disabled={loading}
                >
                  <RotateCcw size={16} />
                  Reset
                </button>
              </div>

              {error && (
                <p className="error" id="area-selection-error" role="alert">{error}</p>
              )}
            </form>
          </div>

          {/* RISK CHART */}
          <div className="panel chart-panel">
            <div className="panel-heading">
              <div>
                <h2>Risk Comparison</h2>
                <p>Low = 1 · Medium = 2 · High = 3</p>
              </div>

              <Activity />
            </div>

            <div className="chart-risk-key" aria-label="Risk scale">
              <span className="key-low"><i /> Low</span>
              <span className="key-medium"><i /> Medium</span>
              <span className="key-high"><i /> High</span>
            </div>

            {risks ? (
              <ResponsiveContainer
                width="100%"
                height={260}
              >
                <BarChart data={chartData}>
                  <defs>
                    <linearGradient id="risk-low" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#50E3A4" />
                      <stop offset="100%" stopColor="#218B70" />
                    </linearGradient>
                    <linearGradient id="risk-medium" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#FFC56B" />
                      <stop offset="100%" stopColor="#C8782D" />
                    </linearGradient>
                    <linearGradient id="risk-high" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#FF8587" />
                      <stop offset="100%" stopColor="#C84458" />
                    </linearGradient>
                  </defs>
                  <CartesianGrid
                    strokeDasharray="3 3"
                    vertical={false}
                    stroke="var(--chart-grid)"
                  />

                  <XAxis
                    dataKey="name"
                    tickLine={false}
                    axisLine={false}
                    tick={{ fill: "var(--chart-label)", fontSize: 10 }}
                  />

                  <YAxis
                    domain={[0, 3]}
                    ticks={[1, 2, 3]}
                    tickLine={false}
                    axisLine={false}
                    tick={{ fill: "var(--chart-label)", fontSize: 10 }}
                    tickFormatter={(value) => ({ 1: "Low", 2: "Med", 3: "High" })[value]}
                  />

                  <Tooltip
                    cursor={{ fill: "var(--chart-grid)" }}
                    contentStyle={{
                      color: "var(--color-text)",
                      background: "var(--color-surface)",
                      border: "1px solid var(--color-border)",
                      borderRadius: "12px",
                      boxShadow: "var(--shadow-card)"
                    }}
                    formatter={(value) => [
                      value === 3 ? "High risk" : value === 2 ? "Medium risk" : "Low risk",
                      "Predicted level"
                    ]}
                  />

                  <Bar
                    dataKey="score"
                    radius={[8, 8, 2, 2]}
                    animationDuration={850}
                  >
                    {chartData.map((entry) => (
                      <Cell
                        key={entry.name}
                        fill={entry.risk ? `url(#risk-${entry.risk.toLowerCase()})` : "transparent"}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="chart-empty">
                <Activity size={35} />

                <p>
                  Risk chart will appear after prediction.
                </p>
              </div>
            )}

            {risks && (
              <p className="chart-note">
                Risk categories are ordinal labels, not measured
                failure probabilities.
              </p>
            )}
          </div>
        </section>

        {/* PREDICTION NOTICE */}
        {risks && (
          <section className="result-note">
            <AlertTriangle size={20} />

            <div>
              <strong>Demo model notice</strong>
              <p>{risks.source}</p>
            </div>
          </section>
        )}
        </>}
        {/* AI PREVENTIVE RECOMMENDATIONS */}
{currentPage.path === "/risk-reports" && <>
  <section className="report-summary-grid" aria-label="Risk report summary">
    {["High", "Medium", "Low"].map((level) => {
      const count = wardData.filter((ward) => getOverallRisk(ward) === level).length;
      return <StatCard key={level} tone={level.toLowerCase()} label={`${level} overall risk`} value={wardLoading ? "—" : count} note={`of ${wardLoading ? "—" : wardData.length} monitored areas`} />;
    })}
    <StatCard label="Assessment export" value={risks ? "Ready" : "Awaiting"} note={risks ? `For ${form.ward_name}` : "Run an AI prediction to export details"} />
  </section>
  <section className="report-content-grid">
    <div className="panel report-chart-panel">
      <div className="panel-heading"><div><h2>Service risk distribution</h2><p>Latest dataset-based ward predictions by service</p></div><FileChartColumnIncreasing size={20} /></div>
      {wardLoading ? <div className="loading-state"><span className="loading-spinner" /> Loading risk distribution...</div> : wardError ? <p className="error-message">{wardError}</p> : (
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={serviceRiskDistribution}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--chart-grid)" />
            <XAxis dataKey="service" tickLine={false} axisLine={false} tick={{ fill: "var(--chart-label)", fontSize: 11 }} />
            <YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fill: "var(--chart-label)", fontSize: 10 }} />
            <Tooltip contentStyle={{ color: "var(--color-text)", background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: 12 }} />
            <Bar dataKey="High" stackId="risk" fill="var(--risk-high)" radius={[4, 4, 0, 0]} />
            <Bar dataKey="Medium" stackId="risk" fill="var(--risk-medium)" />
            <Bar dataKey="Low" stackId="risk" fill="var(--risk-low)" radius={[0, 0, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      )}
      <p className="chart-note">Area risk classifications are model outputs from the synthetic demonstration dataset, not verified real-world conditions.</p>
    </div>
    <div className="panel report-actions-panel">
      <div className="panel-heading"><div><h2>Export assessment</h2><p>Download the selected area's saved risk assessment</p></div><Download size={19} /></div>
      <div className="report-export-summary"><span className="report-export-icon"><ShieldCheck size={19} /></span><div><strong>{risks ? form.ward_name : "No current assessment"}</strong><small>{risks ? "Prediction results and recommendations will be included." : "Generate a prediction before exporting an assessment."}</small></div></div>
      <button className="download-report-button" type="button" onClick={downloadRiskReport} disabled={!risks}><Download size={16} /> Download Excel report</button>
    </div>
  </section>
  <section className="panel area-risk-report-panel">
    <div className="panel-heading"><div><h2>Area-wise risk analysis</h2><p>Latest available model output for each supported area</p></div><MapPin size={20} /></div>
    {wardLoading ? <div className="loading-state"><span className="loading-spinner" /> Loading area analysis...</div> : wardError ? <p className="error-message">{wardError}</p> : (
      <div className="table-wrapper"><table className="ward-table"><thead><tr><th>Area</th><th>Water</th><th>Waste</th><th>Drainage</th><th>Overall</th><th>Data date</th></tr></thead><tbody>
        {wardData.map((ward) => <tr key={ward.ward_name}><td><strong>{ward.ward_name}</strong></td><td><span className={`risk-badge ${ward.water_risk.toLowerCase()}`}>{ward.water_risk}</span></td><td><span className={`risk-badge ${ward.waste_risk.toLowerCase()}`}>{ward.waste_risk}</span></td><td><span className={`risk-badge ${ward.drainage_risk.toLowerCase()}`}>{ward.drainage_risk}</span></td><td><span className={`risk-badge ${getOverallRisk(ward).toLowerCase()}`}>{getOverallRisk(ward)}</span></td><td>{ward.date}</td></tr>)}
      </tbody></table></div>
    )}
  </section>
  </>}
{currentPage.path === "/risk-reports" && risks && (
  <section className="panel recommendation-panel" id="risk-reports">
    <div className="panel-heading recommendation-heading">
  <div>
    <h2>Preventive Action Recommendations</h2>
    <p>Suggested actions based on predicted service risks</p>
  </div>

  <div className="recommendation-actions">
    <ShieldCheck />
  </div>
</div>

    <div className="recommendation-grid">
      {getRecommendations().length > 0 ? (
        getRecommendations().map((item) => (
          <div
            className="recommendation-card"
            key={item.service}
          >
            <div className="recommendation-header">
  <h3>{item.service}</h3>

  <div className="recommendation-badges">
    <span className={`risk-badge ${item.risk.toLowerCase()}`}>
      {item.risk} Risk
    </span>

    <span className={`priority-badge ${item.priority.toLowerCase()}`}>
      {item.priority} Priority
    </span>
  </div>
</div>

            <h4>Recommended Actions</h4>

            <ul>
              {item.actions.map((action, index) => (
                <li key={index}>{action}</li>
              ))}
            </ul>
          </div>
        ))
      ) : (
        <p>No preventive actions required based on the current Low Risk predictions. Continue routine monitoring.</p>
      )}
    </div>

    <p className="chart-note">
      Recommendations are illustrative rule-based suggestions.
      Verify conditions before taking operational action.
    </p>
  </section>
)}

        {/* PREDICTION HISTORY */}
        {currentPage.path === "/prediction-history" && <>
        <section className="panel history-panel" id="prediction-history">
          <div className="panel-heading history-panel-heading">
            <div>
              <span className="section-kicker">PERSISTENT PREDICTION LOG</span>
              <h2>Prediction History</h2>
              <p>Every successful AI assessment, saved for review.</p>
            </div>
            <button
              className="history-refresh-button"
              type="button"
              onClick={fetchPredictionHistory}
              disabled={historyLoading}
            >
              <RefreshCw size={14} className={historyLoading ? "spin" : ""} />
              {historyLoading ? "Refreshing..." : "Refresh"}
            </button>
          </div>

          <div className="history-overview">
            <div className="history-total-card">
              <span className="history-overview-icon"><HistoryIcon size={17} /></span>
              <div>
                <small>TOTAL PREDICTIONS MADE</small>
                <strong>{historyTotal}</strong>
              </div>
            </div>

            <div className="history-latest-card">
              <span className="history-overview-icon"><CalendarClock size={17} /></span>
              <div>
                <small>LATEST PREDICTION</small>
                <strong>
                  {latestPrediction
                    ? formatPredictionDateTime(latestPrediction.prediction_datetime)
                    : "No predictions yet"}
                </strong>
                {latestPrediction && (
                  <span>{getPredictionArea(latestPrediction)}</span>
                )}
              </div>
            </div>
          </div>

          <div className="history-toolbar">
            <label className="history-search-wrap" aria-label="Filter prediction history by area">
              <Search size={15} aria-hidden="true" />
              <select
                aria-label="Filter prediction history by area"
                value={historySearch}
                onChange={(event) => setHistorySearch(event.target.value)}
              >
                <option value="All">All supported areas</option>
                {SUPPORTED_AREAS.map((area) => <option key={area} value={area}>{area}</option>)}
              </select>
            </label>

            <label className="history-risk-filter">
              <span>Risk level</span>
              <select
                aria-label="Filter prediction history by overall risk"
                value={historyRiskFilter}
                onChange={(event) => setHistoryRiskFilter(event.target.value)}
              >
                <option value="All">All risk levels</option>
                <option value="High">High risk</option>
                <option value="Medium">Medium risk</option>
                <option value="Low">Low risk</option>
              </select>
            </label>
          </div>

          {historyActionError && (
            <p className="history-error" role="alert">{historyActionError}</p>
          )}
          {historyError && (
            <p className="history-error" role="alert">{historyError}</p>
          )}

          {historyLoading ? (
            <div className="history-loading">
              <span className="history-loading-orbit"><HistoryIcon size={18} /></span>
              <strong>Syncing prediction records</strong>
              <span>Connecting to the CivicPredict archive...</span>
            </div>
          ) : filteredHistory.length > 0 ? (
            <div className="history-table-wrap">
              <table className="history-table">
                <thead>
                  <tr>
                    <th>Area</th>
                    <th>Prediction date &amp; time</th>
                    <th>Water</th>
                    <th>Waste</th>
                    <th>Drainage</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredHistory.map((prediction) => (
                    <tr key={prediction.prediction_id}>
                      <td>
                        <strong className="history-area-name">
                          {getPredictionArea(prediction)}
                        </strong>
                        <small>Record #{prediction.prediction_id}</small>
                      </td>
                      <td>{formatPredictionDateTime(prediction.prediction_datetime)}</td>
                      <td>
                        <span className={`risk-badge ${prediction.water_supply_risk.toLowerCase()}`}>
                          {prediction.water_supply_risk}
                        </span>
                      </td>
                      <td>
                        <span className={`risk-badge ${prediction.waste_management_risk.toLowerCase()}`}>
                          {prediction.waste_management_risk}
                        </span>
                      </td>
                      <td>
                        <span className={`risk-badge ${prediction.drainage_risk.toLowerCase()}`}>
                          {prediction.drainage_risk}
                        </span>
                      </td>
                      <td>
                        <div className="history-row-actions">
                          <button
                            className="history-details-button"
                            type="button"
                            aria-label={`View details for ${getPredictionArea(prediction)} prediction`}
                            onClick={() => viewPredictionDetails(prediction)}
                          >
                            <Eye size={14} />
                            Details
                          </button>
                          {(authUser.role === "administrator" || prediction.requested_by === authUser.user_id) && (
                            <button
                              className="history-delete-button"
                              type="button"
                              aria-label={`Delete ${getPredictionArea(prediction)} prediction`}
                              disabled={historyDeletingId === prediction.prediction_id}
                              onClick={() => deletePredictionHistoryItem(prediction)}
                            >
                              {historyDeletingId === prediction.prediction_id
                                ? <LoaderCircle size={14} className="spin" />
                                : <Trash2 size={14} />}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="history-empty">
              <span className="history-empty-icon"><HistoryIcon size={23} /></span>
              <h3>{predictionHistory.length ? "No matching predictions" : "Your prediction log starts here"}</h3>
              <p>
                {predictionHistory.length
                  ? "Try changing the area search or risk filter."
                  : "Successful AI assessments will appear here automatically."}
              </p>
            </div>
          )}

          {selectedPrediction && (
            <div className="history-modal-backdrop">
              <section
                className="history-detail-modal"
                role="dialog"
                aria-modal="true"
                aria-labelledby="history-detail-title"
              >
                <div className="history-detail-heading">
                  <div>
                    <span className="section-kicker">PREDICTION RECORD #{selectedPrediction.prediction_id}</span>
                    <h2 id="history-detail-title">{getPredictionArea(selectedPrediction)}</h2>
                    <p>{formatPredictionDateTime(selectedPrediction.prediction_datetime)}</p>
                  </div>
                  <button
                    className="history-modal-close"
                    type="button"
                    aria-label="Close prediction details"
                    onClick={() => setSelectedPrediction(null)}
                  >
                    <X size={17} />
                  </button>
                </div>

                {historyDetailsError && (
                  <p className="history-error" role="alert">{historyDetailsError}</p>
                )}
                {historyDetailsLoading ? (
                  <div className="loading-state">
                    <span className="loading-spinner" />
                    Loading saved prediction details...
                  </div>
                ) : (
                  <>
                    <div className="history-detail-risks">
                      {[
                        ["Water Supply", selectedPrediction.water_supply_risk],
                        ["Waste Management", selectedPrediction.waste_management_risk],
                        ["Drainage", selectedPrediction.drainage_risk]
                      ].map(([label, risk]) => (
                        <div className={`history-detail-risk ${risk.toLowerCase()}`} key={label}>
                          <span>{label}</span>
                          <strong>{risk} Risk</strong>
                        </div>
                      ))}
                    </div>

                    <div className="history-detail-grid">
                      {[
                        ["Rainfall", `${selectedPrediction.rainfall_mm} mm`],
                        ["Temperature", `${selectedPrediction.temperature_c} °C`],
                        ["Humidity", `${selectedPrediction.humidity_pct}%`],
                        ["Water supply hours", selectedPrediction.water_supply_hours],
                        ["Water pressure", selectedPrediction.water_pressure],
                        ["Missed pickups", selectedPrediction.missed_pickups],
                        ["Collection / week", selectedPrediction.collection_frequency_per_week],
                        ["Complaints", selectedPrediction.complaints_count],
                        ["Pipeline age", `${selectedPrediction.pipeline_age_years} years`],
                        ["Drainage capacity", `${selectedPrediction.drainage_capacity_pct}%`],
                        ["Previous repairs", selectedPrediction.previous_repairs_6m]
                      ].map(([label, value]) => (
                        <div key={label}>
                          <span>{label}</span>
                          <strong>{value}</strong>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </section>
            </div>
          )}
        </section>
        </>}

        {/* GOA AREA RISK MONITORING */}
        {currentPage.path === "/ward-monitoring" && <>
        <section className="panel ward-panel" id="ward-monitoring">

          <div className="panel-heading">
            <div>
              <h2>Goa Area Risk Monitoring</h2>
              <p>
                AI-powered predictions across monitored areas
              </p>
            </div>

            <MapPin />
          </div>

          {/* SUMMARY CARDS */}
          <div className="ward-summary">

            <div>
              <strong>{wardLoading ? "—" : wardData.length}</strong>
              <span>Areas monitored</span>
            </div>

            <div>
              <strong>
                {wardLoading ? "—" : wardData.filter(
                  w => getOverallRisk(w) === "High"
                ).length}
              </strong>
              <span>High-risk areas</span>
            </div>

            <div>
              <strong>
                {wardLoading ? "—" : wardData.filter(
                  w => getOverallRisk(w) === "Medium"
                ).length}
              </strong>
              <span>Medium-risk areas</span>
            </div>

            <div>
              <strong>
                {wardLoading ? "—" : wardData.filter(
                  w => getOverallRisk(w) === "Low"
                ).length}
              </strong>
              <span>Low-risk areas</span>
            </div>

          </div>
          {/* RISK FILTER BUTTONS */}
<div className="risk-filter-buttons">
  {["All", "High", "Medium", "Low"].map((risk) => (
    <button
      key={risk}
      className={`filter-btn ${risk.toLowerCase()} ${
        riskFilter === risk ? "selected" : ""
      }`}
      onClick={() => setRiskFilter(risk)}
      type="button"
    >
      {risk === "All" ? "All Areas" : `${risk} Risk`}
    </button>
  ))}
</div>

          {/* SEARCH AREA */}
          <label className="ward-search-wrap" aria-label="Filter monitored area">
            <Search size={17} aria-hidden="true" />
            <select
              className="ward-search"
              aria-label="Filter monitored area"
              value={wardSearch}
              onChange={(e) => setWardSearch(e.target.value)}
            >
              <option value="All">All supported areas</option>
              {SUPPORTED_AREAS.map((area) => <option key={area} value={area}>{area}</option>)}
            </select>
          </label>

          {/* LOADING / ERROR / TABLE */}
          {wardLoading ? (
            <div className="loading-state"><span className="loading-spinner" /> Loading area predictions...</div>
          ) : wardError ? (
            <p className="error">{wardError}</p>
          ) : (
            <div className="table-wrapper">

              <table className="ward-table">

                <thead>
                  <tr>
                    <th>Area</th>
                    <th>Water</th>
                    <th>Waste</th>
                    <th>Drainage</th>
                    <th>Overall Risk</th>
                    <th>Data Date</th>
                  </tr>
                </thead>

                <tbody>
                  {filteredWards.map((ward) => (
                    <tr key={ward.ward_name}>

                      <td>
                        <strong>{ward.ward_name}</strong>
                      </td>

                      <td>
                        <span className={`risk-badge ${ward.water_risk.toLowerCase()}`}>
                          {ward.water_risk}
                        </span>
                      </td>

                      <td>
                        <span className={`risk-badge ${ward.waste_risk.toLowerCase()}`}>
                          {ward.waste_risk}
                        </span>
                      </td>

                      <td>
                        <span className={`risk-badge ${ward.drainage_risk.toLowerCase()}`}>
                          {ward.drainage_risk}
                        </span>
                      </td>

                      <td>
                        <span className={`risk-badge ${getOverallRisk(ward).toLowerCase()}`}>
                          {getOverallRisk(ward)}
                        </span>
                      </td>

                      <td>{ward.date}</td>

                    </tr>
                  ))}
                </tbody>

              </table>

              {filteredWards.length === 0 && (
                <p>No matching areas found.</p>
              )}

            </div>
          )}

          <p className="chart-note">
            Source: Synthetic demo dataset. Predictions are
            illustrative, not verified real-world risk assessments.
          </p>

        </section>
        
        <section className="panel map-panel">
  <div className="panel-heading">
    <div>
      <h2>Goa Risk Monitoring Map</h2>
      <p>Explore predicted public service risks across monitored areas.</p>
    </div>
    <div className="map-live-tag"><span className="status-dot" /> DEMO DATASET · 15 AREAS</div>
  </div>

  <div className="map-legend">
    <span className="high"><i style={{ background: "var(--risk-high)" }}></i> High Risk</span>
    <span className="medium"><i style={{ background: "var(--risk-medium)" }}></i> Medium Risk</span>
    <span className="low"><i style={{ background: "var(--risk-low)" }}></i> Low Risk</span>
  </div>

  <div className="map-container">
    <MapContainer
      center={[15.4, 73.9]}
      zoom={7}
      scrollWheelZoom={true}
      style={{ width: "100%" }}
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />

      {filteredWards.map((ward) => {
        const coordinates = goaCoordinates[ward.ward_name];

        if (!coordinates) return null;

        const overallRisk = getOverallRisk(ward);
        const markerColor = getRiskColor(overallRisk, theme);

        return (
          <CircleMarker
            key={ward.ward_name}
            center={coordinates}
            radius={10}
            pathOptions={{
              color: markerColor,
              fillColor: markerColor,
              fillOpacity: 0.9,
              weight: 3,
              className: `map-risk-marker risk-marker-${overallRisk.toLowerCase()}`,
            }}
          >
            <Popup>
              <div className="map-popup">
                <div className="map-popup-title">
                  <span className="map-popup-pin"><MapPin size={15} /></span>
                  <div>
                    <strong>{ward.ward_name}</strong>
                    <small>Goa monitoring node</small>
                  </div>
                </div>
                <div className={`popup-overall risk-${overallRisk.toLowerCase()}`}>
                  <span className="popup-risk-dot" />
                  {overallRisk} overall risk
                </div>
                <div className="popup-risk-grid">
                  <span>Water</span>
                  <strong className={`risk-text-${ward.water_risk.toLowerCase()}`}>{ward.water_risk}</strong>
                  <span>Waste</span>
                  <strong className={`risk-text-${ward.waste_risk.toLowerCase()}`}>{ward.waste_risk}</strong>
                  <span>Drainage</span>
                  <strong className={`risk-text-${ward.drainage_risk.toLowerCase()}`}>{ward.drainage_risk}</strong>
                </div>
                <small className="map-popup-date">Data date · {ward.date}</small>
              </div>
            </Popup>
          </CircleMarker>
        );
      })}
    </MapContainer>
  </div>

  <p className="map-disclaimer">
    Note: Markers show approximate town-centre locations, not official ward boundaries.
    Predictions use a synthetic demonstration dataset.
  </p>
</section>
        </>}

        {/* FOOTER */}
        <footer>
          CivicPredict AI · Predictive Public Service Failure Prevention System
        </footer>

      </main>
    </div>
  );
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="*" element={<CivicPredictApp />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
