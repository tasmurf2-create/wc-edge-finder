const chartNode = document.getElementById("movement-chart");
if (chartNode && chartNode.dataset.chart && window.Plotly) {
  Plotly.newPlot(chartNode, JSON.parse(chartNode.dataset.chart).data, JSON.parse(chartNode.dataset.chart).layout, { responsive: true });
}
