import {defineConfig} from "@playwright/test";
import configuration from "./playwright.config";
export default defineConfig({...configuration,testMatch:"**/restored.restore.ts"});
