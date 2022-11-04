#
# Copyright (c) 2022, NVIDIA CORPORATION.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

from typing import List

import pytest
from pyspark.sql import SparkSession

from sparkcuml.cluster import SparkCumlKMeans, SparkCumlKMeansModel


def test_kmeans_parameters(spark: SparkSession, gpu_number: int) -> None:
    """
    Sparkcuml keeps the algorithmic parameters and their default values
    exactly the same as cuml multi-node multi-GPU KMeans,
    which follows scikit-learn convention.
    Please refer to https://docs.rapids.ai/api/cuml/stable/api.html#cuml.dask.cluster.KMeans
    """

    default_kmeans = SparkCumlKMeans()
    assert default_kmeans.getOrDefault("n_clusters") == 8
    assert default_kmeans.getOrDefault("max_iter") == 300
    assert default_kmeans.getOrDefault("tol") == 1e-4
    assert default_kmeans.getOrDefault("verbose") == False
    assert default_kmeans.getOrDefault("random_state") == 1
    assert default_kmeans.getOrDefault("init") == "scalable-k-means++"
    assert default_kmeans.getOrDefault("oversampling_factor") == 2
    assert default_kmeans.getOrDefault("max_samples_per_batch") == 32768

    assert default_kmeans.getOrDefault("num_workers") == 1
    assert default_kmeans.get_num_workers() == 1

    custom_params = {
        "n_clusters": 10,
        "max_iter": 100,
        "tol": 1e-1,
        "verbose": True,
        "random_state": 5,
        "init": "k-means||",
        "oversampling_factor": 3,
        "max_samples_per_batch": 45678,
    }

    custom_kmeans = SparkCumlKMeans(**custom_params)

    for key in custom_params:
        assert custom_kmeans.getOrDefault(key) == custom_params[key]


def assert_centers_equal(
    a_clusters: List[List[float]], b_clusters: List[List[float]], tolerance: float
) -> None:
    assert len(a_clusters) == len(b_clusters)
    a_clusters.sort(key=lambda l: l)
    b_clusters.sort(key=lambda l: l)
    for i in range(len(a_clusters)):
        a_center = a_clusters[i]
        b_center = b_clusters[i]
        assert len(a_center) == len(b_center)
        assert a_center == pytest.approx(b_center, tolerance)


def test_toy_example(spark: SparkSession, gpu_number: int) -> None:
    data = [[1.0, 1.0], [1.0, 2.0], [3.0, 2.0], [4.0, 3.0]]

    rdd = spark.sparkContext.parallelize(data).map(lambda row: (row,))
    df = rdd.toDF(["features"])

    sparkcuml_kmeans = SparkCumlKMeans(num_workers=1, n_clusters=2).setFeaturesCol(
        "features"
    )
    sparkcuml_model = sparkcuml_kmeans.fit(df)

    assert len(sparkcuml_model.cluster_centers_) == 2
    sorted_centers = sorted(sparkcuml_model.cluster_centers_, key=lambda p: p)
    assert sorted_centers[0] == pytest.approx([1.0, 1.5], 0.001)
    assert sorted_centers[1] == pytest.approx([3.5, 2.5], 0.001)


def test_compare_cuml(spark: SparkSession, gpu_number: int) -> None:
    """
    The dataset of this test case comes from cuml:
    https://github.com/rapidsai/cuml/blob/496f1f155676fb4b7d99aeb117cbb456ce628a4b/python/cuml/tests/test_kmeans.py#L39
    """
    from cuml.datasets import make_blobs

    n_rows = 1000
    n_cols = 50
    n_clusters = 8
    cluster_std = 1.0
    tolerance = 0.001

    data, _ = make_blobs(
        n_rows, n_cols, n_clusters, cluster_std=cluster_std, random_state=0
    )  # make_blobs creates a random dataset of isotropic gaussian blobs.
    data = data.tolist()

    from cuml import KMeans

    cuml_kmeans = KMeans(n_clusters=n_clusters, output_type="numpy")

    import cudf

    gdf = cudf.DataFrame(data)
    cuml_kmeans.fit(gdf)

    rdd = spark.sparkContext.parallelize(data).map(lambda row: (row,))
    df = rdd.toDF(["features"])
    sparkcuml_kmeans = SparkCumlKMeans(
        num_workers=gpu_number, n_clusters=n_clusters
    ).setFeaturesCol("features")
    sparkcuml_model = sparkcuml_kmeans.fit(df)

    assert_centers_equal(
        sparkcuml_model.cluster_centers_,
        cuml_kmeans.cluster_centers_.tolist(),
        tolerance,
    )
