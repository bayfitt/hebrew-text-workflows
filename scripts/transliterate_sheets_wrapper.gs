/**
 * Sheets custom function for Charles Loder's hebrew-transliteration package.
 * Package: hebrew-transliteration 2.11.0, MIT license (see LICENSE.md).
 *
 * Sheet formula:
 * =CHARLES_TRANSLITERATE(B2:B501,Schema!$A$3:$C$72,Schema!$A$77:$B$86,Schema!$B$90,Schema!$B$91)
 * Use a separate formula for each block of up to 500 input rows.
 *
 * @customfunction
 */
function CHARLES_TRANSLITERATE(inputRange, schemaTable, cleanupTable,
                               removeApostropheBeforeConsonants, vowelLetters) {
  var lib = globalThis.CharlesHebrew;
  if (!lib || typeof lib.transliterate !== "function") {
    throw new Error("CharlesHebrew library is missing. Add CharlesHebrew.gs to this project.");
  }

  var schema = {};
  var schemaRows = asRows_(schemaTable);
  schemaRows.forEach(function(row) {
    if (!row || row.length < 3 || row[0] === "" || row[0] == null) return;
    var key = String(row[0]);
    var type = String(row[2] || "string").toLowerCase();
    var value = row[1];
    if (type === "json") {
      value = JSON.parse(String(value || ""));
    } else if (type === "boolean") {
      value = typeof value === "boolean" ? value : String(value).toLowerCase() === "true";
    } else if (type === "number") {
      value = Number(value);
    } else if (value == null) {
      value = "";
    } else {
      value = String(value);
    }
    schema[key] = value;
  });

  var cleanupRows = asRows_(cleanupTable);
  var rules = cleanupRows
    .filter(function(row) { return row && row[0] !== "" && row[0] != null; })
    .map(function(row) { return [String(row[0]), String(row[1] == null ? "" : row[1])]; })
    .sort(function(a, b) { return b[0].length - a[0].length; });

  var vowels = new Set(Array.from(String(vowelLetters || "aeiouāēīōū").toLowerCase()));
  var shouldCleanSheva = removeApostropheBeforeConsonants === true ||
    String(removeApostropheBeforeConsonants).toLowerCase() === "true";

  function one_(value) {
    if (value == null || value === "") return "";
    var output = lib.transliterate(String(value), schema);
    rules.forEach(function(rule) {
      if (rule[0] !== "") output = output.split(rule[0]).join(rule[1]);
    });
    if (shouldCleanSheva) {
      var chars = Array.from(output);
      for (var i = 0; i < chars.length - 1; i++) {
        if (chars[i] !== "'") continue;
        var next = chars[i + 1];
        var isLetter = /^[A-Za-z\u00C0-\u024F\u1E00-\u1EFF]$/.test(next);
        if (isLetter && !vowels.has(next.toLowerCase())) chars[i] = "";
      }
      output = chars.join("");
    }
    return output;
  }

  if (!Array.isArray(inputRange)) return one_(inputRange);
  return asRows_(inputRange).map(function(row) {
    return row.map(one_);
  });
}

function asRows_(value) {
  if (!Array.isArray(value)) return [[value]];
  return value.length > 0 && Array.isArray(value[0]) ? value : [value];
}
