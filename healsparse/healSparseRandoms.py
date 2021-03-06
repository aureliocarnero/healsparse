from __future__ import division, absolute_import, print_function
import numpy as np
import healpy as hp
import copy

def makeUniformRandomsFast(sparseMap, nRandom, nsideRandoms=2**23, rng=None):
    """
    Make an array of uniform randoms.

    Parameters
    ----------
    sparseMap: `healsparse.HealSparseMap`
       Sparse map object
    nRandom: `int`
       Number of randoms to generate
    nsideRandoms: `int`, optional
       Nside for pixel centers to select random points
    rng: `np.random.RandomState`, optional
       Pre-set Random number generator.  Default is None.

    Returns
    -------
    raArray: `np.array`
       Float array of RAs (degrees)
    decArray: `np.array`
       Float array of declinations (degrees)
    """

    if rng is None:
        rng = np.random.RandomState()

    # get the valid pixels
    validPixels = sparseMap.validPixels

    # Select which "coarse" valid pixels are selected
    ipnestCoarse = rng.choice(validPixels, size=nRandom, replace=True)

    # What is the bitshift from the sparseMap nside to nsideRandoms?
    bitShift = 2 * int(np.round(np.log(nsideRandoms / sparseMap.nsideSparse) / np.log(2)))

    # The sub-pixels are random from bitShift
    subPixels = rng.randint(0, high=2**bitShift - 1, size=nRandom)

    raRand, decRand = hp.pix2ang(nsideRandoms,
                                 np.left_shift(ipnestCoarse, bitShift) + subPixels,
                                 lonlat=True, nest=True)

    return raRand, decRand

def makeUniformRandoms(sparseMap, nRandom, rng=None):
    """
    Make an array of uniform randoms.

    Parameters
    ----------
    sparseMap: `healsparse.HealSparseMap`
       Sparse map object
    nRandom: `int`
       Number of randoms to generate
    rng: `np.random.RandomState`, optional
       Pre-set Random number generator.  Default is None.

    Returns
    -------
    raArray: `np.array`
       Float array of RAs (degrees)
    decArray: `np.array`
       Float array of declinations (degrees)
    """

    if rng is None:
        rng = np.random.RandomState()

    # Generate uniform points on a unit sphere
    r = 1.0
    minGen = 10000
    maxGen = 1000000

    # What is the z/phi range of the coverage map?
    covMask = sparseMap.coverageMask
    covPix, = np.where(covMask)

    # Get range of coverage pixels
    covTheta, covPhi = hp.pix2ang(sparseMap.nsideCoverage, covPix, nest=True)

    extraBoundary = 2.0 * hp.nside2resol(sparseMap.nsideCoverage)

    raRange = np.clip([np.min(covPhi - extraBoundary),
                       np.max(covPhi + extraBoundary)],
                      0.0, 2.0 * np.pi)
    decRange = np.clip([np.min((np.pi/2. - covTheta) - extraBoundary),
                        np.max((np.pi/2. - covTheta) + extraBoundary)],
                       -np.pi/2., np.pi/2.)

    # Check if we can do things more efficiently by rotating 180 degrees
    # for maps that wrap 0
    rotated = False
    covPhiRot = covPhi + np.pi
    test, = np.where(covPhiRot > 2.0 * np.pi)
    covPhiRot[test] -= 2.0 * np.pi
    raRangeRot = np.clip([np.min(covPhiRot - extraBoundary),
                          np.max(covPhiRot + extraBoundary)],
                         0.0, 2.0 * np.pi)
    if ((raRangeRot[1] - raRangeRot[0]) < ((raRange[1] - raRange[0]) - 0.1)):
        # This is a more efficient range in rotated space
        raRange = raRangeRot
        rotated = True

    # And the spherical coverage
    zRange = r * np.sin(decRange)
    phiRange = raRange

    raRand = np.zeros(nRandom)
    decRand = np.zeros(nRandom)

    nLeft = copy.copy(nRandom)
    ctr = 0

    # We have to have a loop here because we don't know
    # how many points will fall in the mask
    while (nLeft > 0):
        # Limit the number of points in each loop
        nGen = np.clip(nLeft * 2, minGen, maxGen)

        z = rng.uniform(low=zRange[0], high=zRange[1], size=nGen)
        phi = rng.uniform(low=phiRange[0], high=phiRange[1], size=nGen)
        theta = np.arcsin(z / r)

        raRandTemp = np.degrees(phi)
        decRandTemp = np.degrees(theta)

        if rotated:
            raRandTemp -= 180.0
            raRandTemp[raRandTemp < 0.0] += 360.0

        valid, = np.where(sparseMap.getValueRaDec(raRandTemp, decRandTemp, validMask=True))
        nValid = valid.size

        if nValid > nLeft:
            nValid = nLeft

        raRand[ctr: ctr + nValid] = raRandTemp[valid[0: nValid]]
        decRand[ctr: ctr + nValid] = decRandTemp[valid[0: nValid]]

        ctr += nValid
        nLeft -= nValid

    return raRand, decRand
