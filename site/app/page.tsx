import { ForecastDashboard, type ForecastData } from "@/components/ForecastDashboard";
import type { ResultsData } from "@/components/ResultsReview";
import forecastData from "@/lib/forecast-data.json";
import resultsData from "@/lib/results-data.json";

export default function Home() {
  return <ForecastDashboard data={forecastData as unknown as ForecastData} results={resultsData as unknown as ResultsData} />;
}
