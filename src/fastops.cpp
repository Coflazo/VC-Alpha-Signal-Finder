// Hot numeric paths, in C++ because they dominate wall-clock at scale.
//
// Three operations, chosen by measurement rather than instinct. Everything else in
// this codebase is IO-bound and would gain nothing from being rewritten.
//
//   cosine_matrix   Every candidate against every thesis vector. At 100k
//                   candidates and 1024 dimensions this is ~1e9 float operations,
//                   which is minutes in Python and well under a second here.
//
//   minhash         Near-duplicate detection. Pairwise comparison is O(N^2);
//                   MinHash signatures plus LSH banding make it O(N) expected.
//                   The inner loop hashes every shingle of every document, which
//                   is exactly the kind of work Python is worst at.
//
//   top_k           Partial selection in O(N log K) rather than a full O(N log N)
//                   sort, and without materialising the sorted array.
//
// Every function here has a pure-Python twin in fastpath.py. The twins are the
// specification: the tests assert the two agree, because a rewrite you cannot
// check against the original is a rewrite you cannot trust.

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/numpy.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <queue>
#include <string>
#include <vector>

namespace py = pybind11;

namespace {

// FNV-1a. Chosen over anything fancier because MinHash needs speed and
// independence between seeds, not cryptographic strength.
inline uint64_t fnv1a(const std::string& s, uint64_t seed) {
    uint64_t h = 1469598103934665603ULL ^ seed;
    for (unsigned char c : s) {
        h ^= c;
        h *= 1099511628211ULL;
    }
    return h;
}

// Word shingles. Word-level rather than character-level because a repost usually
// preserves words while reflowing whitespace and punctuation.
std::vector<std::string> shingles(const std::string& text, size_t k) {
    std::vector<std::string> words;
    std::string cur;
    for (char c : text) {
        if (std::isalnum(static_cast<unsigned char>(c))) {
            cur += static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
        } else if (!cur.empty()) {
            words.push_back(cur);
            cur.clear();
        }
    }
    if (!cur.empty()) words.push_back(cur);

    std::vector<std::string> out;
    if (words.size() < k) {
        if (!words.empty()) {
            std::string joined = words[0];
            for (size_t i = 1; i < words.size(); ++i) joined += " " + words[i];
            out.push_back(joined);
        }
        return out;
    }
    out.reserve(words.size() - k + 1);
    for (size_t i = 0; i + k <= words.size(); ++i) {
        std::string sh = words[i];
        for (size_t j = 1; j < k; ++j) sh += " " + words[i + j];
        out.push_back(sh);
    }
    return out;
}

}  // namespace

// Cosine of one query against every row of a matrix.
//
// The compiler vectorises these loops given -O3; they are written as simple
// contiguous accumulations precisely so that it can. Norms are computed once per
// row rather than repeatedly, which is the mistake the Python version makes.
py::array_t<double> cosine_matrix(py::array_t<double, py::array::c_style | py::array::forcecast> mat,
                                  py::array_t<double, py::array::c_style | py::array::forcecast> query) {
    auto m = mat.unchecked<2>();
    auto q = query.unchecked<1>();
    const ssize_t rows = m.shape(0), dims = m.shape(1);

    if (q.shape(0) != dims) {
        throw std::runtime_error("query dimension does not match matrix");
    }

    double qnorm = 0.0;
    for (ssize_t d = 0; d < dims; ++d) qnorm += q(d) * q(d);
    qnorm = std::sqrt(qnorm);

    auto result = py::array_t<double>(rows);
    auto r = result.mutable_unchecked<1>();

    if (qnorm == 0.0) {
        for (ssize_t i = 0; i < rows; ++i) r(i) = 0.0;
        return result;
    }

    for (ssize_t i = 0; i < rows; ++i) {
        double dot = 0.0, norm = 0.0;
        for (ssize_t d = 0; d < dims; ++d) {
            const double v = m(i, d);
            dot += v * q(d);
            norm += v * v;
        }
        norm = std::sqrt(norm);
        r(i) = (norm > 0.0) ? dot / (norm * qnorm) : 0.0;
    }
    return result;
}

// MinHash signature: the minimum hash of any shingle, under each of `perms`
// independent hash seeds. The probability two signatures agree at a position is
// the Jaccard similarity of the underlying shingle sets, which is what makes this
// an estimator rather than a heuristic.
std::vector<uint64_t> minhash(const std::string& text, size_t perms, size_t k) {
    std::vector<uint64_t> sig(perms, UINT64_MAX);
    const auto sh = shingles(text, k);
    if (sh.empty()) return sig;

    for (const auto& s : sh) {
        for (size_t p = 0; p < perms; ++p) {
            const uint64_t h = fnv1a(s, p * 0x9E3779B97F4A7C15ULL);
            if (h < sig[p]) sig[p] = h;
        }
    }
    return sig;
}

// Estimated Jaccard similarity: the fraction of signature positions that agree.
double signature_similarity(const std::vector<uint64_t>& a,
                            const std::vector<uint64_t>& b) {
    if (a.empty() || a.size() != b.size()) return 0.0;
    size_t same = 0;
    for (size_t i = 0; i < a.size(); ++i) same += (a[i] == b[i]);
    return static_cast<double>(same) / static_cast<double>(a.size());
}

// LSH band hashes. Two documents share a band hash with probability rising sharply
// around a similarity threshold set by the band/row split, so candidate pairs can
// be found by grouping rather than by comparing everything to everything.
std::vector<uint64_t> band_hashes(const std::vector<uint64_t>& sig, size_t bands) {
    std::vector<uint64_t> out;
    if (sig.empty() || bands == 0 || bands > sig.size()) return out;
    const size_t rows = sig.size() / bands;
    out.reserve(bands);
    for (size_t b = 0; b < bands; ++b) {
        uint64_t h = 1469598103934665603ULL;
        for (size_t r = 0; r < rows; ++r) {
            h ^= sig[b * rows + r];
            h *= 1099511628211ULL;
        }
        out.push_back(h);
    }
    return out;
}

// Indices of the k largest values, in descending order.
// A bounded min-heap keeps this O(N log K) and O(K) in space, against O(N log N)
// and O(N) for a full sort.
std::vector<size_t> top_k(const std::vector<double>& values, size_t k) {
    if (k == 0 || values.empty()) return {};
    k = std::min(k, values.size());

    using Item = std::pair<double, size_t>;
    std::priority_queue<Item, std::vector<Item>, std::greater<Item>> heap;

    for (size_t i = 0; i < values.size(); ++i) {
        if (heap.size() < k) {
            heap.emplace(values[i], i);
        } else if (values[i] > heap.top().first) {
            heap.pop();
            heap.emplace(values[i], i);
        }
    }

    std::vector<size_t> out(heap.size());
    for (size_t i = heap.size(); i-- > 0;) {
        out[i] = heap.top().second;
        heap.pop();
    }
    return out;
}

// Cosine against vectors still in their stored form: packed float32 blobs, exactly
// as sqlite returns them.
//
// The obvious binding, taking a Python list-of-lists, measured only 2x faster than
// pure Python because converting 2000x1024 Python float objects into an array costs
// more than the arithmetic does. The bottleneck was marshalling, not maths. Reading
// the bytes directly skips creating those objects at all, which is the difference
// between a wrapper and an actual speedup.
std::vector<std::vector<double>> cosine_blobs(
        const std::vector<py::bytes>& blobs,
        const std::vector<std::vector<double>>& queries) {

    const size_t nq = queries.size();
    std::vector<double> qnorms(nq, 0.0);
    for (size_t j = 0; j < nq; ++j) {
        double s = 0.0;
        for (double v : queries[j]) s += v * v;
        qnorms[j] = std::sqrt(s);
    }

    std::vector<std::vector<double>> out;
    out.reserve(blobs.size());

    for (const auto& blob : blobs) {
        py::buffer_info info(py::buffer(blob).request());
        const float* data = static_cast<const float*>(info.ptr);
        const size_t dims = static_cast<size_t>(info.size) / sizeof(float);

        double norm = 0.0;
        for (size_t d = 0; d < dims; ++d) norm += double(data[d]) * double(data[d]);
        norm = std::sqrt(norm);

        std::vector<double> row(nq, 0.0);
        for (size_t j = 0; j < nq; ++j) {
            if (norm == 0.0 || qnorms[j] == 0.0 || queries[j].size() != dims) continue;
            double dot = 0.0;
            for (size_t d = 0; d < dims; ++d) dot += double(data[d]) * queries[j][d];
            row[j] = dot / (norm * qnorms[j]);
        }
        out.push_back(std::move(row));
    }
    return out;
}

PYBIND11_MODULE(_fastops, m) {
    m.doc() = "Hot numeric paths for vc_alpha. Pure-Python twins live in fastpath.py.";
    m.def("cosine_matrix", &cosine_matrix, py::arg("matrix"), py::arg("query"));
    m.def("cosine_blobs", &cosine_blobs, py::arg("blobs"), py::arg("queries"));
    m.def("minhash", &minhash, py::arg("text"), py::arg("perms") = 128, py::arg("k") = 3);
    m.def("signature_similarity", &signature_similarity, py::arg("a"), py::arg("b"));
    m.def("band_hashes", &band_hashes, py::arg("signature"), py::arg("bands") = 16);
    m.def("top_k", &top_k, py::arg("values"), py::arg("k"));
}
