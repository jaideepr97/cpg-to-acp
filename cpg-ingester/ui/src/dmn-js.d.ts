declare module 'dmn-js' {
  interface DmnViewerOptions {
    container?: HTMLElement;
  }

  export default class DmnViewer {
    constructor(options?: DmnViewerOptions);
    importXML(xml: string): Promise<{ warnings: string[] }>;
    destroy(): void;
  }
}
