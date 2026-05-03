const fs = require('fs');
const path = require('path');

const dataDir = path.join(__dirname, 'frontend', 'public', 'data');
const files = ['map_data_predictions.geojson', 'map_data_predictions_ntr.geojson'];

for (const file of files) {
  const filePath = path.join(dataDir, file);
  if (fs.existsSync(filePath)) {
    console.log(`\n=== Checking ${file} ===`);
    const data = JSON.parse(fs.readFileSync(filePath, 'utf8'));
    const features = data.features || [];
    console.log(`Total features: ${features.length}`);
    
    // Sample first 2 features to see their structure
    features.slice(0, 2).forEach((f, idx) => {
      console.log(`\n--- Feature ${idx} properties ---`);
      const props = f.properties || {};
      console.log('village_id:', props.village_id);
      console.log('village_name:', props.village_name);
      console.log('predicted_groundwater_level:', props.predicted_groundwater_level);
      console.log('forecast_3m:', props.forecast_3m);
      console.log('forecast_3_month:', props.forecast_3_month);
      console.log('forecast_yearly:', props.forecast_yearly);
      console.log('risk_level:', props.risk_level);
      console.log('confidence:', props.confidence);
    });
    
    // Count how many have forecast data
    const withForecast = features.filter(f => f.properties && (f.properties.forecast_3m || f.properties.forecast_3_month));
    console.log(`\nFeatures with forecast_3m or forecast_3_month: ${withForecast.length}`);
  }
}
