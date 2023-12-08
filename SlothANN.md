# SlothANN (WIP)
In the realm of AI, data analysis, and information retrieval, the efficient storage and comparison of vectors has become  central challenges for many. Enter SlothANN, a solution designed to tackle this fundamental problem using semantic knowledge graphs.

## Semantic Graphs 
A semantic knowledge graph, often simply referred to as a knowledge graph, is a structured representation of knowledge that captures the relationships between entities and concepts in a domain. It is a graph-based data model that organizes information in a way that makes it easy to understand and query, emphasizing the semantic meaning of the data.

Semantic graphs have been used in production since the early 2000s, when Google introduced the Knowledge Graph to help improve the speed and accuracy of web search.

At their core, semantic graphs help improve search results by forming a graph representation of different types of data (the nodes) and the relationships between them (the edges).

## Vectors Do Search Too
While semantic graphs are great for representing texts that are similar to each other, vectors produced from sophisticated machine learning models can improve on relating similarity in what we could call "improved levels of abstraction", which we say are abstractions that fall outside the ability for most semantic graphs to represent. 

Using vectors for storing a ton of data sounds good, but it can quickly turn into a headache. See, the more vectors you pile up, the harder it gets to keep things accessible and fast. Traditional methods hit a wall when dealing with big, complex data because they run into scalability problems, especially with high-dimensional data. The trouble comes from how some calculations work, like the cosine distance - it's precise but starts dragging its feet when there are too many vectors to handle. So, efficiency often takes a hit, and that's where the real problems start.

## Enter the Sloth
SlothANN is a real problem solver in the data world. It combines semantic graphs and keyterms to handle a big issue with finding stuff in heaps of data. See, when you've got loads of data, finding specific things in it can be a real headache, especially when those things are high-dimensional vectors.

So, what's SlothANN all about? Well, it's like the brains behind your data searches. As your data gets organized, it builds this smart semantic graph of vectors, all managed by a big language model (LLM). This combo makes your searches smarter and more aware of what's going on, and the best part is, it can handle a boatload of data without breaking a sweat.

But here's what's cool: SlothANN isn't one-size-fits-all. It's like a toolbox where you can fine-tune how it arranges your vectors. You decide how you want speed, accuracy, or a bit of both.

And it's not just limited to one way of looking at your data, either. You can customize it to crawl through your data and find exactly what you're looking for. Using SQL to set conditions, you're in control, optimizing how long it takes to sift through those vectors.

Plus, it's all about teamwork. SlothANN works great with generative models, including OpenAI, Llama2, Bard, Claude and others using set operations to handle even the slowest vector comparisons with ease. So, no matter how much stuff you've got, it handles it like a champ.

Just remember, SlothANN relies on keyterm extraction to build its smart graphs for sorting through the vector space. How fast it works depends on the kind of model you use and how it handles things asynchronously.

If you would prefer to use this solution directly, head on over to https://ai.featurebase.com/ to get started.

## Implementation Requirements
We assume the system is capable of receiving text and embedding the text as a dense vector. OpenAI embeddings return vectors with 1,536 elements and open models like Instructor-Large return vectors with 768 elements.

### Keyterm Prompting
We also assume the code is capable of extracting keyterms from the text. Whichever model you use, the following template may be hopefully used to return a Python dictionary (as a string) that contains the 'keyterms' key and array of keyterms as its value from a single text:

```
# complete dict task
1. Build an entry for the dictionary that has a 'text' key for the following text:
"""
$text
"""
3. Build an entry for the dictionary that has a 'keyterms' key for an array of up to (5) keyterms from the text: in step 1.
python_dict =
```

Note: We assume the system processes $text blocks of ~512 characters per entry. We choose this value because some open embedding models have 512 as a token limit for processing, and we (naively) assume 1 token per character.

From a string similar to `"There was a knock at the door, then silence."` we are given:

```
{
  "keyterms": ['door', 'silence', 'sudden', 'knock']
}
```

### Fast Set Operations
Finally, we assume the use of a datastore capable of rapid set operations on the keyterms and graph nodes, such as FeatureBase, PostgeSAL's Threads, or Apache Druid.

These sets will be used to build a list of followers, leaders and outliers.

## Defining Outliers
An outlier refers to an observation or data point that significantly deviates from the rest of the data in a dataset. Outliers are often unusual, rare, or anomalous in some way and can have a substantial impact on statistical analysis and machine learning models if not handled properly.

In SlothANN, outliers are assumed to meet the conditions that they a) follow a leader, AND b) not have followers, OR c) they do not follow a leader or have followers. The last type outliers will always be limited to the load incurred by the distance calculation function in the system.

## Implementing Entrities
Entrities, are entries that represent entities, which themselves can carry text, sets (for graphs) and vectors. We create them using a simple definition in SQL:

```
CREATE TABLE entrities (entry_id _id, outlier boolean, text string, keyterms stringset, vector(N));
```

Entrities that are outliers are considered *radical* outliers. Radical outliers are always considered during search, and their numbers are limited by the load of the required query to find them:

```
SELECT _id, embedding FROM textstable WHERE outlier = true;
```

If the load of the comparative operation on the embedding vector in returned results exceeds the desired load threshold  then we begin the process of turning some of those outliers into leaders. [rebalance_1]

## Implementing Leaders 
Leaders, who may be of a refined type of radical outlier, are again implemented with sets and are stored in a separate table we create to track them:

```
CREATE TABLE leaders (entrity_id _id, outlier boolean, follows stringset, followers stringset)
```

We initialize a leader with an existing entrity's ID and whether or not the leader is currently considered a leader outlier. If the leader is evaluated to NOT be an outlier, through a comparison on it's outlier value, we assume that the leader has followers and it follows another leader.

### Outlier Operations on 1s and 0s
There is no more efficient operation than on a raw binary digit as done earlier to find radical outlier entrities. Outlier entrities who are "normal" can be returned almost as quickly from the system using a stacked boolean operation on the leaders table:

```
SELECT entrity_id FROM leaders WHERE outlier = true AND (follows = null OR followers = null);
```

We can use this to access the entrity non-radical outliers directly and almost as fast as the radical ones:

```
SELECT t1._id, t1.text, t1.embedding
FROM texttable AS t1
INNER JOIN leaders AS t2 ON t1._id = t2.entrity_id
WHERE t2.outlier = true AND (t2.follows IS NULL OR t2.followers IS NULL);
```

If the load of the comparison operation on the vectors returned from this query exceeds a given load value, we begin the process of turning some of these outliers into leaders. We classify the outliers as either follower outliers or leader outliers.

## Entry Processing
When a new record arrives, we initially consider it an outlier and move to insert it into the datastore. There is only one thing that will stop us from doing this, and that is load on the system:

```
SELECT 




Search leaders:
SELECT text, field_1, cosine_distance(SELECT text, embedding FROM usertable WHERE graph = 'leaders_at5z', embedding) AS distance FROM usertable ORDER BY distance ASC);
Pseudo code to rebalance:
if execution_time > 500ms:
    SELECT text, tanimoto_similarty(SELECT text, keyterms FROM usertable WHERE graph = 'leaders_1'
