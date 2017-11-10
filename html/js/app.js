function cookie (key, value, options) {
  if (arguments.length > 1 && String(value) !== "[object Object]") {
    options = $.extend({}, options);
    if (value === null || value === undefined) {
        options.expires = -1;
    }
    if (typeof options.expires === "number") {
        var days = options.expires,
            t = options.expires = new Date;
        t.setDate(t.getDate() + days);
    }
    value = String(value);
    return document.cookie = [encodeURIComponent(key), "=", options.raw ? value : encodeURIComponent(value), options.expires ? "; expires=" + options.expires.toUTCString() : "", options.path ? "; path=" + options.path : "; path=/", options.domain ? "; domain=" + options.domain : "", options.secure ? "; secure" : ""].join("");
  }
  options = value || {};
  var decode = options.raw ? function(s) {
      return s;
    } : decodeURIComponent,
    result = (new RegExp("(?:^|; )" + encodeURIComponent(key) + "=([^;]*)")).exec(document.cookie);
  return result && result[1] && result[1] !== "null" ? decode(result[1]) : null;
}


$(function(){

});
