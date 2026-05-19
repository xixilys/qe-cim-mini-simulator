#include <algorithm>
#include <cmath>
#include <complex>
#include <cctype>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace fs = std::filesystem;
using Complex = std::complex<double>;

struct Json {
    enum class Type { Null, Bool, Number, String, Array, Object } type = Type::Null;
    bool b = false;
    double n = 0.0;
    std::string s;
    std::vector<Json> a;
    std::map<std::string, Json> o;
};

class Parser {
public:
    explicit Parser(std::string text) : text_(std::move(text)) {}
    Json parse() {
        Json value = parse_value();
        skip_ws();
        if (pos_ != text_.size()) throw std::runtime_error("trailing_json_content");
        return value;
    }
private:
    std::string text_;
    size_t pos_ = 0;

    void skip_ws() {
        while (pos_ < text_.size() && std::isspace(static_cast<unsigned char>(text_[pos_]))) ++pos_;
    }
    char peek() { skip_ws(); return pos_ < text_.size() ? text_[pos_] : '\0'; }
    char get() { return pos_ < text_.size() ? text_[pos_++] : '\0'; }
    void expect(char c) {
        skip_ws();
        if (get() != c) throw std::runtime_error(std::string("expected_") + c);
    }
    Json parse_value() {
        skip_ws();
        char c = peek();
        if (c == '{') return parse_object();
        if (c == '[') return parse_array();
        if (c == '"') { Json v; v.type = Json::Type::String; v.s = parse_string(); return v; }
        if (c == 't' || c == 'f') return parse_bool();
        if (c == 'n') return parse_null();
        return parse_number();
    }
    Json parse_null() {
        if (text_.substr(pos_, 4) != "null") throw std::runtime_error("bad_null");
        pos_ += 4;
        return Json{};
    }
    Json parse_bool() {
        Json v; v.type = Json::Type::Bool;
        if (text_.substr(pos_, 4) == "true") { v.b = true; pos_ += 4; return v; }
        if (text_.substr(pos_, 5) == "false") { v.b = false; pos_ += 5; return v; }
        throw std::runtime_error("bad_bool");
    }
    Json parse_number() {
        skip_ws();
        size_t start = pos_;
        if (pos_ < text_.size() && (text_[pos_] == '-' || text_[pos_] == '+')) ++pos_;
        while (pos_ < text_.size() && std::isdigit(static_cast<unsigned char>(text_[pos_]))) ++pos_;
        if (pos_ < text_.size() && text_[pos_] == '.') {
            ++pos_;
            while (pos_ < text_.size() && std::isdigit(static_cast<unsigned char>(text_[pos_]))) ++pos_;
        }
        if (pos_ < text_.size() && (text_[pos_] == 'e' || text_[pos_] == 'E')) {
            ++pos_;
            if (pos_ < text_.size() && (text_[pos_] == '-' || text_[pos_] == '+')) ++pos_;
            while (pos_ < text_.size() && std::isdigit(static_cast<unsigned char>(text_[pos_]))) ++pos_;
        }
        if (start == pos_) throw std::runtime_error("bad_number");
        Json v; v.type = Json::Type::Number; v.n = std::stod(text_.substr(start, pos_ - start)); return v;
    }
    std::string parse_string() {
        expect('"');
        std::string out;
        while (pos_ < text_.size()) {
            char c = get();
            if (c == '"') break;
            if (c == '\\') {
                char e = get();
                switch (e) {
                    case '"': out.push_back('"'); break;
                    case '\\': out.push_back('\\'); break;
                    case '/': out.push_back('/'); break;
                    case 'b': out.push_back('\b'); break;
                    case 'f': out.push_back('\f'); break;
                    case 'n': out.push_back('\n'); break;
                    case 'r': out.push_back('\r'); break;
                    case 't': out.push_back('\t'); break;
                    case 'u': {
                        // Boundary-array artifacts are ASCII; preserve a placeholder for unicode escapes.
                        for (int i = 0; i < 4 && pos_ < text_.size(); ++i) ++pos_;
                        out.push_back('?');
                        break;
                    }
                    default: out.push_back(e); break;
                }
            } else {
                out.push_back(c);
            }
        }
        return out;
    }
    Json parse_array() {
        Json v; v.type = Json::Type::Array; expect('['); skip_ws();
        if (peek() == ']') { get(); return v; }
        while (true) {
            v.a.push_back(parse_value());
            skip_ws();
            char c = get();
            if (c == ']') break;
            if (c != ',') throw std::runtime_error("bad_array_separator");
        }
        return v;
    }
    Json parse_object() {
        Json v; v.type = Json::Type::Object; expect('{'); skip_ws();
        if (peek() == '}') { get(); return v; }
        while (true) {
            std::string key = parse_string();
            expect(':');
            v.o[key] = parse_value();
            skip_ws();
            char c = get();
            if (c == '}') break;
            if (c != ',') throw std::runtime_error("bad_object_separator");
        }
        return v;
    }
};

static std::string read_text(const fs::path& path) {
    std::ifstream in(path);
    if (!in) throw std::runtime_error("cannot_open:" + path.string());
    std::ostringstream ss; ss << in.rdbuf(); return ss.str();
}

static const Json* get(const Json& obj, const std::string& key) {
    if (obj.type != Json::Type::Object) return nullptr;
    auto it = obj.o.find(key);
    return it == obj.o.end() ? nullptr : &it->second;
}
static const Json* get_path(const Json& obj, std::initializer_list<const char*> path) {
    const Json* cur = &obj;
    for (const char* key : path) {
        cur = get(*cur, key);
        if (!cur) return nullptr;
    }
    return cur;
}
static double as_num(const Json* v, double def = 0.0) {
    if (!v) return def;
    if (v->type == Json::Type::Number) return v->n;
    if (v->type == Json::Type::Bool) return v->b ? 1.0 : 0.0;
    if (v->type == Json::Type::String) {
        try { return std::stod(v->s); } catch (...) { return def; }
    }
    return def;
}
static int as_int(const Json* v, int def = 0) { return static_cast<int>(std::llround(as_num(v, def))); }
static std::string as_str(const Json* v, std::string def = "") {
    if (!v) return def;
    if (v->type == Json::Type::String) return v->s;
    if (v->type == Json::Type::Number) { std::ostringstream ss; ss << v->n; return ss.str(); }
    if (v->type == Json::Type::Bool) return v->b ? "true" : "false";
    return def;
}
static std::vector<double> num_array(const Json* v) {
    std::vector<double> out;
    if (!v || v->type != Json::Type::Array) return out;
    for (const auto& item : v->a) out.push_back(as_num(&item));
    return out;
}
static std::vector<int> int_array(const Json* v) {
    std::vector<int> out;
    if (!v || v->type != Json::Type::Array) return out;
    for (const auto& item : v->a) out.push_back(as_int(&item));
    return out;
}
static std::vector<Complex> complex_pairs(const Json* v) {
    std::vector<Complex> out;
    if (!v || v->type != Json::Type::Array) return out;
    for (const auto& item : v->a) {
        if (item.type == Json::Type::Array && item.a.size() >= 2) out.emplace_back(as_num(&item.a[0]), as_num(&item.a[1]));
        else out.emplace_back(0.0, 0.0);
    }
    return out;
}
static double l2(const std::vector<Complex>& values) {
    long double sum = 0.0;
    for (const auto& v : values) sum += std::norm(v);
    return std::sqrt(static_cast<double>(sum));
}
static double max_abs(const std::vector<Complex>& values) {
    double out = 0.0;
    for (const auto& v : values) out = std::max(out, std::abs(v));
    return out;
}
static std::string json_escape(const std::string& s) {
    std::string out;
    for (char c : s) {
        switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default: out.push_back(c); break;
        }
    }
    return out;
}
static size_t idxF(int x, int y, int z, int nx, int ny) { return static_cast<size_t>(x + nx * (y + ny * z)); }

static void transform_axis(std::vector<Complex>& data, int nx, int ny, int nz, int axis, bool inverse) {
    const double pi = std::acos(-1.0);
    int len = axis == 0 ? nx : (axis == 1 ? ny : nz);
    std::vector<Complex> input(len), output(len);
    int outer0 = axis == 0 ? ny : nx;
    int outer1 = axis == 2 ? ny : nz;
    for (int a = 0; a < outer0; ++a) {
        for (int b = 0; b < outer1; ++b) {
            for (int i = 0; i < len; ++i) {
                int x = axis == 0 ? i : a;
                int y = axis == 0 ? a : (axis == 1 ? i : b);
                int z = axis == 2 ? i : b;
                input[i] = data[idxF(x, y, z, nx, ny)];
            }
            for (int k = 0; k < len; ++k) {
                Complex sum(0.0, 0.0);
                for (int j = 0; j < len; ++j) {
                    double angle = 2.0 * pi * static_cast<double>(j * k) / static_cast<double>(len);
                    Complex w = std::polar(1.0, inverse ? angle : -angle);
                    sum += input[j] * w;
                }
                output[k] = inverse ? sum / static_cast<double>(len) : sum;
            }
            for (int i = 0; i < len; ++i) {
                int x = axis == 0 ? i : a;
                int y = axis == 0 ? a : (axis == 1 ? i : b);
                int z = axis == 2 ? i : b;
                data[idxF(x, y, z, nx, ny)] = output[i];
            }
        }
    }
}
static std::vector<Complex> fft3(std::vector<Complex> data, int nx, int ny, int nz, bool inverse) {
    transform_axis(data, nx, ny, nz, 0, inverse);
    transform_axis(data, nx, ny, nz, 1, inverse);
    transform_axis(data, nx, ny, nz, 2, inverse);
    return data;
}

struct Result {
    std::vector<Complex> hpsi;
    std::vector<std::string> blockers;
    double abs_error = 0.0;
    double rel_error = 0.0;
    double max_error = 0.0;
    int lda = 0, n = 0, m = 0, npol = 1;
};

static Result compute_full_hpsi(const Json& root) {
    Result r;
    r.lda = as_int(get_path(root, {"dimensions", "lda"}));
    r.n = as_int(get_path(root, {"dimensions", "n"}));
    r.m = as_int(get_path(root, {"dimensions", "m"}));
    r.npol = as_int(get(root, "npol"), 1);
    if (r.lda <= 0 || r.n <= 0 || r.m <= 0) r.blockers.push_back("invalid_dimensions_for_native_hpsi");
    if (r.npol != 1) r.blockers.push_back("native_hpsi_npol_not_supported:" + std::to_string(r.npol));
    const int element_count = r.lda * std::max(1, r.npol) * r.m;
    auto psi = complex_pairs(get(root, "psi_real_imag"));
    auto reference = complex_pairs(get(root, "hpsi_reference_real_imag"));
    auto g2kin = num_array(get(root, "g2kin"));
    if (static_cast<int>(psi.size()) != element_count) r.blockers.push_back("psi_array_length_mismatch:" + std::to_string(psi.size()) + ":" + std::to_string(element_count));
    if (static_cast<int>(reference.size()) != element_count) r.blockers.push_back("hpsi_reference_array_length_mismatch:" + std::to_string(reference.size()) + ":" + std::to_string(element_count));
    if (static_cast<int>(g2kin.size()) < r.lda) r.blockers.push_back("g2kin_array_length_mismatch:" + std::to_string(g2kin.size()) + ":" + std::to_string(r.lda));

    std::string vloc_path = as_str(get_path(root, {"vloc_algorithm", "path"}));
    if (vloc_path != "vloc_psi_k_acc") r.blockers.push_back("vloc_algorithm_path_not_supported_for_native_hpsi:" + (vloc_path.empty() ? std::string("missing") : vloc_path));
    std::string vnl_path = as_str(get_path(root, {"vnl_inputs", "algorithm_path"}));
    if (vnl_path != "add_vuspsi_k") r.blockers.push_back("vnl_algorithm_path_not_supported_for_native_hpsi:" + (vnl_path.empty() ? std::string("missing") : vnl_path));
    if (!r.blockers.empty()) return r;

    std::vector<Complex> kinetic(element_count, Complex(0.0, 0.0));
    for (int band = 0; band < r.m; ++band) {
        int base = band * r.lda;
        for (int row = 0; row < r.lda; ++row) {
            kinetic[base + row] = row < r.n ? psi[base + row] * g2kin[row] : Complex(0.0, 0.0);
        }
    }

    const int nnr = as_int(get_path(root, {"fft_descriptor_dffts", "nnr"}));
    auto nrx = int_array(get_path(root, {"fft_descriptor_dffts", "nrx"}));
    auto nr = int_array(get_path(root, {"fft_descriptor_dffts", "nr"}));
    auto shape = nrx.size() == 3 ? nrx : nr;
    if (shape.size() != 3 || shape[0] <= 0 || shape[1] <= 0 || shape[2] <= 0 || shape[0] * shape[1] * shape[2] != nnr) {
        r.blockers.push_back("fft_descriptor_shape_product_mismatch:" + std::to_string(nnr));
        return r;
    }
    auto vrs = num_array(get_path(root, {"vloc_inputs", "vrs_current_spin"}));
    auto igk = int_array(get_path(root, {"vloc_inputs", "igk_current_k"}));
    auto dffts_nl = int_array(get_path(root, {"vloc_inputs", "dffts_nl"}));
    if (static_cast<int>(vrs.size()) != nnr) r.blockers.push_back("vrs_current_spin_length_mismatch:" + std::to_string(vrs.size()) + ":" + std::to_string(nnr));
    if (static_cast<int>(igk.size()) < r.n) r.blockers.push_back("igk_current_k_length_mismatch:" + std::to_string(igk.size()) + ":" + std::to_string(r.n));
    if (dffts_nl.empty()) r.blockers.push_back("missing_dffts_nl_mapping");
    for (int row = 0; row < r.n && row < static_cast<int>(igk.size()); ++row) {
        int ig = igk[row] - 1;
        if (ig < 0 || ig >= static_cast<int>(dffts_nl.size())) r.blockers.push_back("igk_current_k_refs_missing_dffts_nl");
        else if (dffts_nl[ig] <= 0 || dffts_nl[ig] > nnr) r.blockers.push_back("dffts_nl_position_out_of_range");
    }
    if (!r.blockers.empty()) return r;

    std::vector<Complex> vloc(element_count, Complex(0.0, 0.0));
    for (int band = 0; band < r.m; ++band) {
        std::vector<Complex> reciprocal(nnr, Complex(0.0, 0.0));
        int base = band * r.lda;
        for (int row = 0; row < r.n; ++row) {
            int pos = dffts_nl[igk[row] - 1] - 1;
            reciprocal[pos] = psi[base + row];
        }
        auto realspace = fft3(reciprocal, shape[0], shape[1], shape[2], true);
        for (int i = 0; i < nnr; ++i) realspace[i] *= vrs[i];
        auto back = fft3(realspace, shape[0], shape[1], shape[2], false);
        for (int row = 0; row < r.n; ++row) {
            int pos = dffts_nl[igk[row] - 1] - 1;
            vloc[base + row] = back[pos];
        }
    }

    int nkb = as_int(get_path(root, {"vnl_inputs", "nkb"}));
    int nhm = as_int(get_path(root, {"vnl_inputs", "nhm"}));
    int nat = as_int(get_path(root, {"vnl_inputs", "nat"}));
    auto nh = int_array(get_path(root, {"vnl_inputs", "nh"}));
    auto ityp = int_array(get_path(root, {"vnl_inputs", "ityp"}));
    auto ofsbeta = int_array(get_path(root, {"vnl_inputs", "ofsbeta"}));
    auto vkb_flat = complex_pairs(get_path(root, {"vnl_inputs", "vkb_real_imag"}));
    auto deeq = num_array(get_path(root, {"vnl_inputs", "deeq_current_spin"}));
    if (nkb <= 0 || nhm <= 0 || nat <= 0) r.blockers.push_back("vnl_positive_dimension_missing:" + std::to_string(nkb) + ":" + std::to_string(nhm) + ":" + std::to_string(nat));
    if (static_cast<int>(vkb_flat.size()) != r.lda * nkb) r.blockers.push_back("vkb_array_length_mismatch:" + std::to_string(vkb_flat.size()) + ":" + std::to_string(r.lda * nkb));
    if (static_cast<int>(deeq.size()) != nat * nhm * nhm) r.blockers.push_back("deeq_array_length_mismatch:" + std::to_string(deeq.size()) + ":" + std::to_string(nat * nhm * nhm));
    if (static_cast<int>(ityp.size()) != nat || static_cast<int>(ofsbeta.size()) != nat || nh.empty()) r.blockers.push_back("vnl_atom_index_metadata_missing");
    if (!r.blockers.empty()) return r;

    std::vector<std::vector<Complex>> becp(nkb, std::vector<Complex>(r.m, Complex(0.0, 0.0)));
    for (int kb = 0; kb < nkb; ++kb) {
        for (int band = 0; band < r.m; ++band) {
            Complex sum(0.0, 0.0);
            for (int row = 0; row < r.n; ++row) {
                Complex vkb = vkb_flat[kb * r.lda + row];
                sum += std::conj(vkb) * psi[band * r.lda + row];
            }
            becp[kb][band] = sum;
        }
    }
    std::vector<std::vector<Complex>> ps(nkb, std::vector<Complex>(r.m, Complex(0.0, 0.0)));
    for (int atom = 0; atom < nat; ++atom) {
        int type_index = ityp[atom] - 1;
        if (type_index < 0 || type_index >= static_cast<int>(nh.size())) { r.blockers.push_back("vnl_type_index_out_of_range"); continue; }
        int projector_count = nh[type_index];
        int start = ofsbeta[atom];
        if (start < 0 || start + projector_count > nkb) { r.blockers.push_back("vnl_ofsbeta_range_invalid"); continue; }
        for (int i = 0; i < projector_count; ++i) {
            for (int band = 0; band < r.m; ++band) {
                Complex sum(0.0, 0.0);
                for (int j = 0; j < projector_count; ++j) {
                    double deeaux = deeq[atom * nhm * nhm + j * nhm + i]; // transpose of deeq(atom, :, :)
                    sum += deeaux * becp[start + j][band];
                }
                ps[start + i][band] = sum;
            }
        }
    }
    if (!r.blockers.empty()) return r;
    std::vector<Complex> vnl(element_count, Complex(0.0, 0.0));
    for (int band = 0; band < r.m; ++band) {
        for (int row = 0; row < r.n; ++row) {
            Complex sum(0.0, 0.0);
            for (int kb = 0; kb < nkb; ++kb) sum += vkb_flat[kb * r.lda + row] * ps[kb][band];
            vnl[band * r.lda + row] = sum;
        }
    }

    r.hpsi.resize(element_count);
    for (int i = 0; i < element_count; ++i) r.hpsi[i] = kinetic[i] + vloc[i] + vnl[i];
    std::vector<Complex> err(element_count);
    for (int i = 0; i < element_count; ++i) err[i] = r.hpsi[i] - reference[i];
    r.abs_error = l2(err);
    double ref_l2 = l2(reference);
    r.rel_error = r.abs_error / std::max(ref_l2, 1.0e-300);
    r.max_error = max_abs(err);
    if (!(r.abs_error <= 1.0e-12 || r.rel_error <= 1.0e-12)) {
        std::ostringstream ss; ss << std::scientific << std::setprecision(6) << r.rel_error;
        r.blockers.push_back("native_full_hpsi_numeric_mismatch:" + ss.str());
    }
    return r;
}

static void write_result_txt(const fs::path& path, const std::vector<Complex>& values) {
    fs::create_directories(path.parent_path());
    std::ofstream out(path);
    out << std::scientific << std::setprecision(17);
    for (const auto& v : values) out << v.real() << " " << v.imag() << "\n";
}

static void write_summary(const fs::path& path, const Result& r, const fs::path& arrays, const fs::path& result_txt) {
    fs::create_directories(path.parent_path());
    bool passed = r.blockers.empty() && !r.hpsi.empty();
    std::ofstream out(path);
    out << std::scientific << std::setprecision(17);
    out << "{\n";
    out << "  \"absolute_error\": " << r.abs_error << ",\n";
    out << "  \"blockers\": [";
    for (size_t i = 0; i < r.blockers.size(); ++i) {
        if (i) out << ", ";
        out << "\"" << json_escape(r.blockers[i]) << "\"";
    }
    out << "],\n";
    out << "  \"boundary_arrays\": \"" << json_escape(arrays.string()) << "\",\n";
    out << "  \"claim_boundary\": \"SystemC/GenericAccel model L4 offload plus native C++ kernel numerical evidence; this is not silicon or RTL proof.\",\n";
    out << "  \"component_model_reference_replay_only\": false,\n";
    out << "  \"dimensions\": {\"lda\": " << r.lda << ", \"m\": " << r.m << ", \"n\": " << r.n << ", \"npol\": " << r.npol << "},\n";
    out << "  \"element_count\": " << r.hpsi.size() << ",\n";
    out << "  \"error_metric\": \"full_h_psi_l2_against_qe_reference\",\n";
    out << "  \"full_h_psi_recomputed\": " << (passed ? "true" : "false") << ",\n";
    out << "  \"full_kernel_recomputed\": " << (passed ? "true" : "false") << ",\n";
    out << "  \"host_stage_reference_assisted\": false,\n";
    out << "  \"kernel_id\": \"h_psi\",\n";
    out << "  \"kernel_scope\": \"full_h_psi\",\n";
    out << "  \"max_abs_error\": " << r.max_error << ",\n";
    out << "  \"producer\": \"gem5_generic_accel_qe_hpsi_systemc_native_payload\",\n";
    out << "  \"relative_error\": " << r.rel_error << ",\n";
    out << "  \"result_txt\": \"" << json_escape(result_txt.string()) << "\",\n";
    out << "  \"schema_version\": \"dse.qe_hpsi_l4_native_payload_result.v1\",\n";
    out << "  \"software_component_model_not_l4\": false,\n";
    out << "  \"source\": \"gem5_generic_accel_qe_hpsi_systemc_native_payload\",\n";
    out << "  \"status\": \"" << (passed ? "passed_native_l4_payload" : "blocked") << "\",\n";
    out << "  \"trusted_full_claim\": " << (passed ? "true" : "false") << ",\n";
    out << "  \"trusted_payload_kind\": \"systemc_generic_accel_model_l4_offload_kernel_numerical\"\n";
    out << "}\n";
}

int main(int argc, char** argv) {
    fs::path boundary_arrays, result_txt, summary_json;
    bool quiet = false;
    bool fail_on_blocked = false;
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        auto need = [&](const char* name) -> fs::path {
            if (i + 1 >= argc) throw std::runtime_error(std::string("missing_arg:") + name);
            return fs::path(argv[++i]);
        };
        if (arg == "--boundary-arrays") boundary_arrays = need("--boundary-arrays");
        else if (arg == "--result-txt") result_txt = need("--result-txt");
        else if (arg == "--summary-json") summary_json = need("--summary-json");
        else if (arg == "--quiet") quiet = true;
        else if (arg == "--fail-on-blocked") fail_on_blocked = true;
        else throw std::runtime_error("unknown_arg:" + arg);
    }
    if (boundary_arrays.empty() || result_txt.empty() || summary_json.empty()) {
        std::cerr << "required: --boundary-arrays --result-txt --summary-json\n";
        return 2;
    }
    Result result;
    try {
        Json root = Parser(read_text(boundary_arrays)).parse();
        result = compute_full_hpsi(root);
        if (result.blockers.empty()) write_result_txt(result_txt, result.hpsi);
        else write_result_txt(result_txt, {});
    } catch (const std::exception& exc) {
        result.blockers.push_back(std::string("native_hpsi_exception:") + exc.what());
    }
    write_summary(summary_json, result, boundary_arrays, result_txt);
    if (!quiet) std::cout << read_text(summary_json);
    bool blocked = !result.blockers.empty() || result.hpsi.empty();
    return (fail_on_blocked && blocked) ? 2 : 0;
}
