import { MAP_MODES } from '../constants/mapModes';

export const initialMapState = {
  mode: MAP_MODES.PREDICTION,
};

export function setMapMode(currentMode, newMode) {
  return newMode;
}
