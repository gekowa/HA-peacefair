const { version } = require('../custom_components/peacefair/manifest.json');

// An explicitly bumped manifest is a floor for the next stable release.
// This also allows recovery when a previous release tag is outside main's history.
exports.preVersionGeneration = (recommended) => {
  const parse = (value) => {
    if (!/^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.test(value)) {
      throw new Error(`Invalid stable release version: ${value}`);
    }
    return value.split('.').map(Number);
  };
  const requested = parse(version);
  const automatic = parse(recommended);
  for (let index = 0; index < 3; index++) {
    if (requested[index] > automatic[index]) return version;
    if (requested[index] < automatic[index]) return recommended;
  }
  return recommended;
};
