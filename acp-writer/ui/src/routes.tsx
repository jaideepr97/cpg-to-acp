import { Route, Routes } from "react-router-dom";
import { IpsView } from "@app/pages/IpsView";
import { RunListPage } from "@app/pages/RunListPage";
import { RunDetailPage } from "@app/pages/RunDetailPage";
import { CarePlanList } from "@app/pages/CarePlanList";
import { CarePlanDetail } from "@app/pages/CarePlanDetail";
import { SystemStatus } from "@app/pages/SystemStatus";

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<IpsView />} />
      <Route path="/runs" element={<RunListPage />} />
      <Route path="/runs/:runId" element={<RunDetailPage />} />
      <Route path="/careplans" element={<CarePlanList />} />
      <Route path="/careplans/:id" element={<CarePlanDetail />} />
      <Route path="/status" element={<SystemStatus />} />
    </Routes>
  );
}
