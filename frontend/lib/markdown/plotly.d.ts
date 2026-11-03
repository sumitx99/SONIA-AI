// The partial Plotly builds ship without types; Sonia uses only these calls.
interface PlotlyApi {
  react(element: HTMLElement, data: object[], layout: object, config?: object): Promise<HTMLElement>;
  purge(element: HTMLElement): void;
  downloadImage(element: HTMLElement, options: { format: "png"; filename: string; scale?: number }): Promise<string>;
  Plots: { resize(element: HTMLElement): void };
}

declare module "plotly.js-cartesian-dist-min" { const Plotly: PlotlyApi; export default Plotly; }
declare module "plotly.js-geo-dist-min" { const Plotly: PlotlyApi; export default Plotly; }
declare module "plotly.js-map-dist-min" { const Plotly: PlotlyApi; export default Plotly; }
