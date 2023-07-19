FlorDB: Nimble Experiment Management for Iterative ML
================================

Flor (for "fast low-overhead recovery") is a record-replay system for deep learning, and other forms of machine learning that train models on GPUs. Flor was developed to speed-up hindsight logging: a cyclic-debugging practice that involves adding logging statements *after* encountering a surprise, and efficiently re-training with more logging. Flor takes low-overhead checkpoints during training, or the record phase, and uses those checkpoints for replay speedups based on memoization and parallelism.

FlorDB integrates Flor, `git` and `sqlite3` to manage model developer's logs, execution data, versions of code, and training checkpoints. In addition to serving as an experiment management solution for ML Engineers, FlorDB extends hindsight logging across model trainging versions for the retroactive evaluation of iterative ML.

Flor and FlorDB are software developed at UC Berkeley's [RISE](https://rise.cs.berkeley.edu/) Lab.

[![Napa Retreat Demo](https://i.ytimg.com/vi/TNSt5-i7kR4/sddefault.jpg)](https://youtu.be/TNSt5-i7kR4)

# Installation

```bash
pip install flordb
```

# Getting Started

We start by selecting (or creating) a `git` repository to save our model training code as we iterate and experiment. Flor automatically commits your changes on every run, so no change is lost. Below we provide a sample repository you can use to follow along:

```bash
git clone git@github.com:ucbepic/ml_tutorial
cd ml_tutorial/
```

Run the `train.py` script to train a small linear model, 
and test your `flordb` installation.

```bash
python train.py --flor myFirstRun
```

Flor will manage checkpoints, logs, command-line arguments, code changes, and other experiment metadata on each run (More details [below](#under-the-hood)). All of this data is then expesed to the user via SQL or Pandas queries.

# View your experiment history
From the same directory you ran the examples above, open an iPython terminal, then load and pivot the log records.

```ipython
In [1]: from flor import full_pivot, log_records
In [2]: full_pivot(log_records())
Out[2]: 
                            projid       runid               tstamp        vid  epoch  step      loss hidden batch_size epochs     lr
0   ml_tutorial_flor.shadow.readme  myFirstRun  2023-07-19T09:01:51  c0418c...      1   100  0.246695    500         32      5  0.001
1   ml_tutorial_flor.shadow.readme  myFirstRun  2023-07-19T09:01:51  c0418c...      1   200  0.279637    500         32      5  0.001
2   ml_tutorial_flor.shadow.readme  myFirstRun  2023-07-19T09:01:51  c0418c...      1   300  0.247390    500         32      5  0.001
3   ml_tutorial_flor.shadow.readme  myFirstRun  2023-07-19T09:01:51  c0418c...      1   400  0.536536    500         32      5  0.001
4   ml_tutorial_flor.shadow.readme  myFirstRun  2023-07-19T09:01:51  c0418c...      1   500  0.198422    500         32      5  0.001
..                             ...         ...                  ...        ...    ...   ...       ...    ...        ...    ...    ...
85  ml_tutorial_flor.shadow.readme  myFirstRun  2023-07-19T09:01:51  c0418c...      5  1400  0.003081    500         32      5  0.001
86  ml_tutorial_flor.shadow.readme  myFirstRun  2023-07-19T09:01:51  c0418c...      5  1500  0.002184    500         32      5  0.001
87  ml_tutorial_flor.shadow.readme  myFirstRun  2023-07-19T09:01:51  c0418c...      5  1600  0.042605    500         32      5  0.001
88  ml_tutorial_flor.shadow.readme  myFirstRun  2023-07-19T09:01:51  c0418c...      5  1700  0.007986    500         32      5  0.001
89  ml_tutorial_flor.shadow.readme  myFirstRun  2023-07-19T09:01:51  c0418c...      5  1800  0.006866    500         32      5  0.001

[90 rows x 11 columns]
```

# Model Training Kit (MTK)
The MTK includes utilities for serializing and checkpointing PyTorch state,
and utilities for resuming, auto-parallelizing, and memoizing executions from checkpoint.
The model developer passes objects for checkpointing to flor,
and gives it control over loop iterators by calling `MTK.checkpoints`
and `MTK.loop` as follows:

```python
from flor import MTK as Flor

import torch

trainloader: torch.utils.data.DataLoader
testloader:  torch.utils.data.DataLoader
optimizer:   torch.optim.Optimizer
net:         torch.nn.Module
criterion:   torch.nn._Loss

Flor.checkpoints(net, optimizer)
for epoch in Flor.loop(range(...)):
    for data in Flor.loop(trainloader):
        inputs, labels = data
        optimizer.zero_grad()
        outputs = net(inputs)
        loss = criterion(outputs, labels)
        loss.backward()
        optimizer.step()
    eval(net, testloader)
```
As shown, we pass the neural network and optimizer to Flor 
for checkpointing with `Flor.checkpoints(net, optimizer)`.
We wrap both the nested training loop and main loop with 
`Flor.loop`. This lets Flor jump to an arbitrary epoch
using checkpointed state, 
and skip the nested training loop when intermediate
state isn't probed.

# Under the hood
On each run, Flor will:
1. Save model checkpoints in `~/.flor/`
1. Commit code changes, command-line args, and log records to `git`, inside a dedicated `flor.shadow` branch.


```bash
(base) ml_tutorial $ ls ~/.flor 
ml_tutorial_flor.shadow.readme

(base) ml_tutorial $ git branch   
* flor.shadow.readme

(base) ml_tutorial $ ls -la ./.flor   
drwxr-xr-x  5 rogarcia   160 Jul 19 09:02 .
drwxr-xr-x  9 rogarcia   288 Jul 19 09:01 ..
-rw-r--r--  1 rogarcia   225 Jul 19 09:02 .replay.json
-rw-r--r--  1 rogarcia  2895 Jul 19 09:02 log_records.csv
-rw-r--r--  1 rogarcia   228 Jul 19 09:02 seconds.json
```
Confirm that Flor saved checkpoints of the `train.py` execution on your home directory (`~`).
Flor will access and interpret contents of `.flor` automatically. The data and log records will be exposed to the user via SQL or Pandas queries.

# Hindsight Logging

```python
from flor import MTK as Flor
import torch

trainloader: torch.utils.data.DataLoader
testloader:  torch.utils.data.DataLoader
optimizer:   torch.optim.Optimizer
net:         torch.nn.Module
criterion:   torch.nn._Loss

for epoch in Flor.loop(range(...)):
    for batch in Flor.loop(trainloader):
        ...
    eval(net, testloader)
    log_confusion_matrix(net, testloader)
```

Suppose you want to view a confusion matrix as it changes
throughout training.
Add the code to generate the confusion matrix, as sugared above.

```bash
python3 mytrain.py --replay_flor PID/NGPUS [your_flags]
```

As before, you tell FLOR to run in replay mode by setting ``--replay_flor``.
You'll also tell FLOR how many GPUs from the pool to use for parallelism,
and you'll dispatch this script simultaneously, varying the ``pid:<int>``
to span all the GPUs. To run segment 3 out of 5 segments, you would write: ``--replay_flor 3/5``.

If instead of replaying all of training you wish to re-execute only a fraction of the epochs
you can do this by setting the value of ``ngpus`` and ``pid`` respectively.
Suppose you want to run the tenth epoch of a training job that ran for 200 epochs. You would set
``pid:9``and ``ngpus:200``.

## Publications

To cite this work, please refer to the [Hindsight Logging](http://www.vldb.org/pvldb/vol14/p682-garcia.pdf) paper (VLDB '21).

FLOR is open source software developed at UC Berkeley. 
[Joe Hellerstein](https://dsf.berkeley.edu/jmh/) (databases), [Joey Gonzalez](http://people.eecs.berkeley.edu/~jegonzal/) (machine learning), and [Koushik Sen](https://people.eecs.berkeley.edu/~ksen) (programming languages) 
are the primary faculty members leading this work.

This work is released as part of [Rolando Garcia](https://rlnsanz.github.io/)'s doctoral dissertation at UC Berkeley,
and has been the subject of study by Eric Liu and Anusha Dandamudi, 
both of whom completed their master's theses on FLOR.
Our list of publications are reproduced below.
Finally, we thank [Vikram Sreekanti](https://www.vikrams.io/), [Dan Crankshaw](https://dancrankshaw.com/), and [Neeraja Yadwadkar](https://cs.stanford.edu/~neeraja/) for guidance, comments, and advice.
[Bobby Yan](https://bobbyy.org/) was instrumental in the development of FLOR and its corresponding experimental evaluation.

* [Hindsight Logging for Model Training](http://www.vldb.org/pvldb/vol14/p682-garcia.pdf). _R Garcia, E Liu, V Sreekanti, B Yan, A Dandamudi, JE Gonzalez, JM Hellerstein, K Sen_. The VLDB Journal, 2021.
* [Fast Low-Overhead Logging Extending Time](https://www2.eecs.berkeley.edu/Pubs/TechRpts/2021/EECS-2021-117.html). _A Dandamudi_. EECS Department, UC Berkeley Technical Report, 2021.
* [Low Overhead Materialization with FLOR](https://www2.eecs.berkeley.edu/Pubs/TechRpts/2020/EECS-2020-79.html). _E Liu_. EECS Department, UC Berkeley Technical Report, 2020. 


## License
FLOR is licensed under the [Apache v2 License](https://www.apache.org/licenses/LICENSE-2.0).
