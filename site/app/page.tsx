import { ForecastDashboard, type ForecastData } from "@/components/ForecastDashboard";
import forecastData from "@/lib/forecast-data.json";

export default function Home() {
  return <ForecastDashboard data={forecastData as unknown as ForecastData} />;
}
