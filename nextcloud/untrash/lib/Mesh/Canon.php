<?php

declare(strict_types=1);

namespace OCA\Untrash\Mesh;

/**
 * Canonical JSON as UntrashOS signs it (cloud-api.md, app-api.md §2):
 * Python json.dumps(sort_keys=True, separators=(",", ":")), ASCII only
 * (\uXXXX, lower-case hex), a top-level "sig" left out.  JSON objects must be
 * decoded as stdClass (json_decode without assoc), so {} and [] stay apart.
 */
class Canon {
    public static function encode($v, bool $top = true): string {
        if ($v instanceof \stdClass) {
            $a = get_object_vars($v);
            if ($top) {
                unset($a['sig']);
            }
            ksort($a, SORT_STRING);
            $out = [];
            foreach ($a as $k => $x) {
                $out[] = self::str((string)$k) . ':' . self::encode($x, false);
            }
            return '{' . implode(',', $out) . '}';
        }
        if (is_array($v)) {
            if ($v !== [] && array_keys($v) !== range(0, count($v) - 1)) {
                return self::encode((object)$v, $top);          // an associative array is an object
            }
            return '[' . implode(',', array_map(function ($x) {
                return self::encode($x, false);
            }, $v)) . ']';
        }
        if (is_string($v)) {
            return self::str($v);
        }
        if (is_bool($v)) {
            return $v ? 'true' : 'false';
        }
        if ($v === null) {
            return 'null';
        }
        if (is_int($v)) {
            return (string)$v;
        }
        throw new \InvalidArgumentException('no floats in signed data');
    }

    private static function str(string $s): string {
        $j = json_encode($s, JSON_UNESCAPED_SLASHES);
        if ($j === false) {
            throw new \InvalidArgumentException('not UTF-8');
        }
        return str_replace("\x7f", '\u007f', $j);            // Python escapes DEL, PHP does not
    }

    public static function b64urlDecode(string $text) {
        $text = preg_replace('/\s+/', '', $text);
        $raw = base64_decode(strtr($text, '-_', '+/') . str_repeat('=', (4 - strlen($text) % 4) % 4), true);
        return $raw === false ? null : json_decode($raw);
    }
}
