from __future__ import division, absolute_import, print_function
import numpy as np
import healpy as hp
import fitsio
import os
from .utils import reduce_array, checkSentinel

class HealSparseMap(object):
    """
    Class to define a HealSparseMap
    """

    def __init__(self, covIndexMap=None, sparseMap=None, nsideSparse=None, healpixMap=None, nsideCoverage=None, primary=None, sentinel=None, nest=True):

        if covIndexMap is not None and sparseMap is not None and nsideSparse is not None:
            # this is a sparse map input
            self._covIndexMap = covIndexMap
            self._sparseMap = sparseMap
        elif healpixMap is not None and nsideCoverage is not None:
            # this is a healpixMap input
            if sentinel is None:
                sentinel = hp.UNSEEN
            self._covIndexMap, self._sparseMap = self.convertHealpixMap(healpixMap,
                                                                        nsideCoverage=nsideCoverage,
                                                                        nest=nest,
                                                                        sentinel=sentinel)
            nsideSparse = hp.npix2nside(healpixMap.size)
        else:
            raise RuntimeError("Must specify either covIndexMap/sparseMap or healpixMap/nsideCoverage")

        self._nsideCoverage = hp.npix2nside(self._covIndexMap.size)
        self._nsideSparse = nsideSparse

        self._isRecArray = False
        self._primary = primary
        if self._sparseMap.dtype.fields is not None:
            self._isRecArray = True
            if self._primary is None:
                raise RuntimeError("Must specify `primary` field when using a recarray for the sparseMap.")

            self._sentinel = checkSentinel(self._sparseMap[self._primary].dtype.type, sentinel)
        else:
            self._sentinel = checkSentinel(self._sparseMap.dtype.type, sentinel)

        self._bitShift = 2 * int(np.round(np.log(self._nsideSparse / self._nsideCoverage) / np.log(2)))

    @classmethod
    def read(cls, filename, nsideCoverage=None, pixels=None, header=False):
        """
        Read in a HealSparseMap.

        Parameters
        ----------
        filename: `str`
           Name of the file to read.  May be either a regular HEALPIX
           map or a HealSparseMap
        nsideCoverage: `int`, optional
           Nside of coverage map to generate if input file is healpix map.
        pixels: `list`, optional
           List of coverage map pixels to read.  Only used if input file
           is a HealSparseMap
        header: `bool`, optional
           Return the fits header as well as map?  Default is False.

        Returns
        -------
        healSparseMap: `HealSparseMap`
           HealSparseMap from file, covered by pixels
        header: `fitsio.FITSHDR` (if header=True)
           Fits header for the map file.
        """

        # Check to see if the filename is a healpix map or a sparsehealpix map

        hdr = fitsio.read_header(filename, ext=1)
        if 'PIXTYPE' in hdr and hdr['PIXTYPE'].rstrip() == 'HEALPIX':
            if nsideCoverage is None:
                raise RuntimeError("Must specify nsideCoverage when reading healpix map")

            # This is a healpix format
            # We need to determine the datatype, preserving it.
            if hdr['OBJECT'].rstrip() == 'PARTIAL':
                row = fitsio.read(filename, ext=1, rows=[0])
                dtype = row[0]['SIGNAL'].dtype.type
            else:
                row = fitsio.read(filename, ext=1, rows=[0])
                dtype = row[0][0][0].dtype.type

            healpixMap = hp.read_map(filename, nest=True, verbose=False, dtype=dtype)
            if header:
                return (cls(healpixMap=healpixMap, nsideCoverage=nsideCoverage, nest=True), hdr)
            else:
                return cls(healpixMap=healpixMap, nsideCoverage=nsideCoverage, nest=True)
        elif 'PIXTYPE' in hdr and hdr['PIXTYPE'].rstrip() == 'HEALSPARSE':
            # This is a sparse map type.  Just use fits for now.
            covIndexMap, sparseMap, nsideSparse, primary, sentinel = cls._readHealSparseFile(filename, pixels=pixels)
            if header:
                return (cls(covIndexMap=covIndexMap, sparseMap=sparseMap, nsideSparse=nsideSparse, primary=primary, sentinel=sentinel), hdr)
            else:
                return cls(covIndexMap=covIndexMap, sparseMap=sparseMap, nsideSparse=nsideSparse, primary=primary, sentinel=sentinel)
        else:
            raise RuntimeError("Filename %s not in healpix or healsparse format." % (filename))

    @classmethod
    def makeEmpty(cls, nsideCoverage, nsideSparse, dtype, primary=None, sentinel=None):
        """
        Make an empty map with nothing in it.

        Parameters
        ----------
        nsideCoverage: `int`
           Nside for the coverage map
        nsideSparse: `int`
           Nside for the sparse map
        dtype: `str` or `list` or `np.dtype`
           Datatype, any format accepted by numpy.
        primary: `str`, optional
           Primary key for recarray, required if dtype has fields.

        Returns
        -------
        healSparseMap: `HealSparseMap`
           HealSparseMap filled with UNSEEN values.
        """

        bitShift = 2 * int(np.round(np.log(nsideSparse / nsideCoverage) / np.log(2)))
        nFinePerCov = 2**bitShift

        covIndexMap = np.zeros(hp.nside2npix(nsideCoverage), dtype=np.int64)
        covIndexMap[:] -= np.arange(hp.nside2npix(nsideCoverage), dtype=np.int64) * nFinePerCov

        sparseMap = np.zeros(nFinePerCov, dtype=dtype)
        if sparseMap.dtype.fields is not None:
            if primary is None:
                raise RuntimeError("Must specify 'primary' field when using a recarray for the sparseMap.")

            primaryFound = False
            for name in sparseMap.dtype.names:
                if name == primary:
                    _sentinel = checkSentinel(sparseMap[name].dtype.type, sentinel)
                    sparseMap[name][:] = _sentinel
                    primaryFound = True
                else:
                    # TODO: Should this be something other than UNSEEN?
                    # And does it matter?
                    sparseMap[name][:] = hp.UNSEEN

            if not primaryFound:
                raise RuntimeError("Primary field not found in input dtype of recarray.")

        else:
            # fill with sentinel value
            _sentinel = checkSentinel(sparseMap.dtype.type, sentinel)
            sparseMap[:] = _sentinel

        return cls(covIndexMap=covIndexMap, sparseMap=sparseMap, nsideSparse=nsideSparse, primary=primary, sentinel=_sentinel)

    @staticmethod
    def _readHealSparseFile(filename, pixels=None):
        """
        Read a healsparse file, optionally with a set of coverage pixels.

        Parameters
        ----------
        filename: `str`
           Name of the file to read.
        pixels: `list`, optional
           List of integer pixels from the coverage map

        Returns
        -------
        covIndexMap: `np.array`
           Integer array for coverage index values
        sparseMap: `np.array`
           Sparse map with map dtype
        nsideSparse: `int`
           Nside of the coverage map
        primary: `str`
           Primary key field for recarray map.  Default is None.
        sentinel: `float` or `int`
           Sentinel value for null.  Usually hp.UNSEEN
        """
        covIndexMap = fitsio.read(filename, ext='COV')
        primary = None

        if pixels is None:
            # Read the full map
            sparseMap, sHdr = fitsio.read(filename, ext='SPARSE', header=True)
            nsideSparse = sHdr['NSIDE']
            if 'PRIMARY' in sHdr:
                primary = sHdr['PRIMARY'].rstrip()
            # If SENTINEL is not there then it should be UNSEEN
            if 'SENTINEL' in sHdr:
                sentinel = sHdr['SENTINEL']
            else:
                sentinel = hp.UNSEEN
        else:
            _pixels = np.atleast_1d(pixels)
            if len(np.unique(_pixels)) < len(_pixels):
                raise RuntimeError("Input list of pixels must be unique.")

            # Read part of a map
            with fitsio.FITS(filename) as fits:

                hdu = fits['SPARSE']
                sHdr = hdu.read_header()

                nsideSparse = sHdr['NSIDE']
                nsideCoverage = hp.npix2nside(covIndexMap.size)

                if 'SENTINEL' in sHdr:
                    sentinel = sHdr['SENTINEL']
                else:
                    sentinel = hp.UNSEEN

                bitShift = 2 * int(np.round(np.log(nsideSparse / nsideCoverage) / np.log(2)))
                nFinePerCov = 2**bitShift

                imageType = False
                if hdu.get_exttype() == 'IMAGE_HDU':
                    # This is an image extension
                    sparseMapSize = hdu.get_dims()[0]
                    imageType = True
                else:
                    # This is a table extension
                    primary = sHdr['PRIMARY'].rstrip()
                    sparseMapSize = hdu.get_nrows()

                nCovPix = sparseMapSize // nFinePerCov - 1

                # This is the map without the offset
                covIndexMapTemp = covIndexMap + np.arange(hp.nside2npix(nsideCoverage), dtype=np.int64) * nFinePerCov
                covPix, = np.where(covIndexMapTemp >= nFinePerCov)

                # Find which pixels are in the coverage map
                sub = np.clip(np.searchsorted(covPix, _pixels), 0, covPix.size - 1)
                ok, = np.where(covPix[sub] == _pixels)
                if ok.size == 0:
                    raise RuntimeError("None of the specified pixels are in the coverage map")
                sub = np.sort(sub[ok])

                # It is not 100% sure this is the most efficient way to read in using
                # fitsio, but it does work.
                sparseMap = np.zeros((sub.size + 1) * nFinePerCov, dtype=fits['SPARSE'][0:1].dtype)
                # Read in the overflow bin
                sparseMap[0: nFinePerCov] = hdu[0: nFinePerCov]
                # And read in the pixels
                for i, pix in enumerate(covPix[sub]):
                    sparseMap[(i + 1)*nFinePerCov: (i + 2)*nFinePerCov] = hdu[covIndexMapTemp[pix]: covIndexMapTemp[pix] + nFinePerCov]

                # Set the coverage index map for the pixels that we read in
                covIndexMap[:] = 0
                covIndexMap[covPix[sub]] = np.arange(1, sub.size + 1) * nFinePerCov
                covIndexMap[:] -= np.arange(hp.nside2npix(nsideCoverage), dtype=np.int64) * nFinePerCov

        return covIndexMap, sparseMap, nsideSparse, primary, sentinel

    @staticmethod
    def convertHealpixMap(healpixMap, nsideCoverage, nest=True, sentinel=hp.UNSEEN):
        """
        Convert a healpix map to a healsparsemap.

        Parameters
        ----------
        healpixMap: `np.array`
           Numpy array that describes a healpix map.
        nsideCoverage: `int`
           Nside for the coverage map to construct
        nest: `bool`, optional
           Is the input map in nest format?  Default is True.
        sentinel: `float`, optional
           Sentinel value for null values in the sparseMap.
           Default is hp.UNSEEN

        Returns
        -------
        covIndexMap: `np.array`
           Coverage map with pixel indices
        sparseMap: `np.array`
           Sparse map of input values.
        """
        if not nest:
            # must convert map to ring format
            healpixMap = hp.reorder(healpixMap, r2n=True)

        # Compute the coverage map...
        # Note that this is coming from a standard healpix map so the sentinel
        # is always hp.UNSEEN
        ipnest, = np.where(healpixMap > hp.UNSEEN)

        bitShift = 2 * int(np.round(np.log(hp.npix2nside(healpixMap.size) / nsideCoverage) / np.log(2)))
        ipnestCov = np.right_shift(ipnest, bitShift)

        covPix = np.unique(ipnestCov)

        nFinePerCov = int(healpixMap.size / hp.nside2npix(nsideCoverage))

        # This initializes as zeros, that's the location of the overflow bins
        covIndexMap = np.zeros(hp.nside2npix(nsideCoverage), dtype=np.int64)

        # The default for the covered pixels is the location in the array (below)
        # Note that we have a 1-index here to have the 0-index overflow bin
        covIndexMap[covPix] = np.arange(1, covPix.size + 1) * nFinePerCov
        # And then subtract off the starting fine pixel for each coarse pixel
        covIndexMap[:] -= np.arange(hp.nside2npix(nsideCoverage), dtype=np.int64) * nFinePerCov

        sparseMap = np.zeros((covPix.size + 1) * nFinePerCov, dtype=healpixMap.dtype) + sentinel
        sparseMap[ipnest + covIndexMap[ipnestCov]] = healpixMap[ipnest]

        return covIndexMap, sparseMap

    def write(self, filename, clobber=False, header=None):
        """
        Write heal HealSparseMap to filename

        Parameters
        ----------
        filename: `str`
           Name of file to save
        clobber: `bool`, optional
           Clobber existing file?  Default is False.
        header: `fitsio.FITSHDR` or `dict`, optional
           Header to put in first extension with additional metadata.
           Default is None.
        """
        if os.path.isfile(filename) and not clobber:
            raise RuntimeError("Filename %s exists and clobber is False." % (filename))

        # Note that we put the requested header information in each of the extensions.
        cHdr = fitsio.FITSHDR(header)
        cHdr['PIXTYPE'] = 'HEALSPARSE'
        cHdr['NSIDE'] = self._nsideCoverage
        fitsio.write(filename, self._covIndexMap, header=cHdr, extname='COV', clobber=True)
        sHdr = fitsio.FITSHDR(header)
        sHdr['PIXTYPE'] = 'HEALSPARSE'
        sHdr['NSIDE'] = self._nsideSparse
        sHdr['SENTINEL'] = self._sentinel
        if self._isRecArray:
            sHdr['PRIMARY'] = self._primary
        fitsio.write(filename, self._sparseMap, header=sHdr, extname='SPARSE')

    def updateValues(self, pixel, values, nest=True):
        """
        Update the values in the sparsemap.

        Parameters
        ----------
        pixel: `np.array`
           Integer array of sparseMap pixel values
        values: `np.array`
           Array of values.  Must be same type as sparseMap
        """

        # First, check if these are the same type
        if not isinstance(values, np.ndarray):
            raise RuntimeError("Values are not a numpy ndarray")

        if not nest:
            _pix = hp.ring2nest(self._nsideSparse, pixel)
        else:
            _pix = pixel

        if self._sparseMap.dtype != values.dtype:
            raise RuntimeError("Data-type mismatch between sparseMap and values")

        # Compute the coverage pixels
        ipnestCov = np.right_shift(_pix, self._bitShift)

        # Check which pixels are in the coverage map
        covMask = self.coverageMask
        inCov, = np.where(covMask[ipnestCov])
        outCov, = np.where(~covMask[ipnestCov])

        # Replace values for those pixels in the coverage map
        self._sparseMap[_pix[inCov] + self._covIndexMap[ipnestCov[inCov]]] = values[inCov]

        # Update the coverage map for the rest of the pixels (if necessary)
        if outCov.size > 0:
            # This requires data copying. (Even numpy appending does)
            # I don't want to overthink this and prematurely optimize, but
            # I want it to be able to work when the map isn't being held
            # in memory.  So that will require an append and non-contiguous
            # pixels, which I *think* should be fine.

            nFinePerCov = 2**self._bitShift

            newCovPix = np.unique(ipnestCov[outCov])
            sparseAppend = np.zeros(newCovPix.size * nFinePerCov, dtype=self._sparseMap.dtype)
            # Fill with the empty defaults (generally UNSEEN)
            sparseAppend[:] = self._sparseMap[0]

            # Update covIndexMap
            # These are pixels that are at the end of the previous sparsemap

            # First reset the map to the base pixel indices
            covIndexMapTemp = self._covIndexMap + np.arange(hp.nside2npix(self._nsideCoverage), dtype=np.int64) * nFinePerCov
            # Put in the appended pixels
            covIndexMapTemp[newCovPix] = np.arange(newCovPix.size) * nFinePerCov + self._sparseMap.size
            # And put the offset back in
            covIndexMapTemp[:] -= np.arange(hp.nside2npix(self._nsideCoverage), dtype=np.int64) * nFinePerCov

            # Fill in the pixels to append
            sparseAppend[_pix[outCov] + covIndexMapTemp[ipnestCov[outCov]] - self._sparseMap.size] = values[outCov]

            # And set the values in the map
            self._covIndexMap = covIndexMapTemp
            self._sparseMap = np.append(self._sparseMap, sparseAppend)

    def getValueRaDec(self, ra, dec, validMask=False):
        """
        Get the map value for a ra/dec in degrees (for now)

        Parameters
        ----------
        ra: `np.array`
           Float array of RA (degrees)
        dec: `np.array`
           Float array of dec (degrees)
        validMask: `bool`, optional
           Return mask of True/False instead of values

        Returns
        -------
        values: `np.array`
           Array of values/validity from the map.
        """

        return self.getValueThetaPhi(np.radians(90.0 - dec), np.radians(ra),
                                     validMask=validMask)

    def getValueThetaPhi(self, theta, phi, validMask=False):
        """
        Get the map value for a theta/phi.

        Parameters
        ----------
        theta: `np.array`
           Float array of healpix theta (np.radians(90.0 - dec))
        phi: `np.array`
           Float array of healpix phi (np.radians(ra))
        validMask: `bool`, optional
           Return mask of True/False instead of values

        Returns
        -------
        values: `np.array`
           Array of values/validity from the map.
        """

        ipnest = hp.ang2pix(self._nsideSparse, theta, phi, nest=True)

        return self.getValuePixel(ipnest, nest=True, validMask=validMask)

    def getValuePixel(self, pixel, nest=True, validMask=False):
        """
        Get the map value for a pixel.

        Parameters
        ----------
        pixel: `np.array`
           Integer array of healpix pixels.
        nest: `bool`, optional
           Are the pixels in nest scheme?  Default is True.
        validMask: `bool`, optional
           Return mask of True/False instead of values

        Returns
        -------
        values: `np.array`
           Array of values/validity from the map.
        """

        if not nest:
            _pix = hp.ring2nest(self._nsideSparse, pixel)
        else:
            _pix = pixel

        ipnestCov = np.right_shift(_pix, self._bitShift)

        values = self._sparseMap[_pix + self._covIndexMap[ipnestCov]]

        if validMask:
            if self._isRecArray:
                return (values[self._primary] > self._sentinel)
            else:
                return (values > self._sentinel)
        else:
            # Just return the values
            return values

    @property
    def dtype(self):
        """
        get the dtype of the map
        """
        return self._sparseMap.dtype

    @property
    def coverageMap(self):
        """
        Get the fractional area covered by the sparse map
        in the resolution of the coverage map

        Returns
        -------
        covMap: `np.array`
           Float array of fractional coverage of each pixel
        """

        covMap = np.zeros_like(self.coverageMask, dtype=np.double)
        covMask = self.coverageMask
        npop_pix = np.count_nonzero(covMask)
        if self._isRecArray:
            spMap_T = self._sparseMap[self._primary].reshape((npop_pix+1, -1))
        else:
            spMap_T = self._sparseMap.reshape((npop_pix+1, -1))
        counts = np.sum((spMap_T > self._sentinel), axis=1).astype(np.double)
        covMap[covMask] = counts[1:] / 2**self._bitShift
        return covMap

    @property
    def coverageMask(self):
        """
        Get the boolean mask of the coverage map.

        Returns
        -------
        covMask: `np.array`
           Boolean array of coverage mask.
        """

        nfine = 2**self._bitShift
        covMask = (self._covIndexMap[:] + np.arange(hp.nside2npix(self._nsideCoverage))*nfine) >= nfine
        return covMask

    @property
    def nsideCoverage(self):
        """
        Get the nside of the coverage map

        Returns
        -------
        nsideCoverage: `int`
        """

        return self._nsideCoverage

    @property
    def nsideSparse(self):
        """
        Get the nside of the sparse map

        Returns
        -------
        nsideSparse: `int`
        """

        return self._nsideSparse

    @property
    def primary(self):
        """
        Get the primary field

        Returns
        -------
        primary: `str`
        """

        return self._primary

    @property
    def isIntegerMap(self):
        """
        Check that the map is an integer map

        Returns
        -------
        isIntegerMap: `bool`
        """

        if self._isRecArray:
            return False

        return issubclass(self._sparseMap.dtype.type, np.integer)

    @property
    def isRecArray(self):
        """
        Check that the map is a recArray map.

        Returns
        -------
        isRecArray: `bool`
        """

        return self._isRecArray

    def generateHealpixMap(self, nside=None, reduction='mean', key=None):
        """
        Generate the associated healpix map

        if nside is specified, then reduce

        Args:
        -----
        nside: `int`
            Output nside resolution parameter (should be a multiple of 2). If not specified
            the output resolution will be equal to the parent's sparsemap nsideSparse
        reduction: `str`
            If a change in resolution is requested, this controls the method to reduce the
            map computing the mean, median, std, max or min of the neighboring pixels to compute
            the `degraded` map.
        key: `str`
            If the parent HealSparseMap contains `recarrays`, key selects the field that will be
            transformed into a HEALPix map.

        Returns:
        --------
        hp_map: `ndarray`
            Output HEALPix map with the requested resolution.
        """

        # If no nside is passed, we generate a map with the same resolution as the original
        if nside is None:
            nside = self._nsideSparse

        if self._isRecArray:
            if key is None:
                raise ValueError('key should be specified for HealSparseMaps including `recarray`')
            else:
                # Note that this makes the code simpler but is memory inefficient
                # We may need to revisit this later depending on use cases
                singleMap = self.getSingle(key)
        else:
            singleMap = self

        # If we're degrading, let that code do the datatyping
        if nside < self._nsideSparse:
            # degrade to new resolution
            singleMap = singleMap.degrade(nside, reduction=reduction)
        elif nside > self._nsideSparse:
            raise ValueError("Cannot generate HEALPix map with higher resolution than the original.")

        # Check to see if we have an integer map.
        if issubclass(singleMap._sparseMap.dtype.type, np.integer):
            dtypeOut = np.float64
        else:
            dtypeOut = singleMap._sparseMap.dtype

        # Create an empty HEALPix map, filled with UNSEEN values
        hpMap = np.zeros(hp.nside2npix(nside), dtype=dtypeOut) + hp.UNSEEN

        validPixels = singleMap.validPixels
        hpMap[validPixels] = singleMap.getValuePixel(validPixels)

        return hpMap

    @property
    def validPixels(self):
        """
        Get an array of valid pixels in the sparse map.

        Returns
        -------
        validPixels: `np.array`
        """

        # Get the coarse pixels that are in the map
        validCoverage, = np.where(self.coverageMask)
        nFinePerCov = 2**self._bitShift

        # For each coarse pixel, this is the starting point for the pixel number
        pixBase = np.left_shift(validCoverage, self._bitShift)

        # Tile/repeat to expand into the full pixel numbers
        # Note that these are all the pixels that are defined in the sparse map,
        # but not all of them are valid
        validPixels = (np.tile(np.arange(nFinePerCov), validCoverage.size) +
                       np.repeat(pixBase, nFinePerCov))

        # And return only the valid subset
        return validPixels[self.getValuePixel(validPixels, validMask=True)]

    def degrade(self, nside_out, reduction='mean'):
        """
        Reduce the resolution, i.e., increase the pixel size
        of a given sparse map.

        Args:
        ----
        nside_out: `int`, output Nside resolution parameter.
        reduction: `str`, reduction method (mean, median, std, max, min).
        """

        if self._nsideSparse < nside_out:
            raise ValueError('nside_out should be smaller than nside for the sparseMap')
        # Count the number of filled pixels in the coverage mask
        npop_pix = np.count_nonzero(self.coverageMask)
        # We need the new bitShifts and we have to build a new CovIndexMap
        bitShift = 2 * int(np.round(np.log(nside_out / self._nsideCoverage) / np.log(2)))
        nFinePerCov = 2**bitShift
        # Work with RecArray (we have to change the resolution to all maps...)
        if self._isRecArray:
            dtype = []
            # We should avoid integers
            for key, value in self._sparseMap.dtype.fields.items():
                if issubclass(self._sparseMap[key].dtype.type, np.integer):
                    dtype.append((key, np.float64))
                else:
                    dtype.append((key, value[0]))
            # Allocate new map
            newsparseMap = np.zeros((npop_pix+1)*nFinePerCov, dtype=dtype)
            for key, value in newsparseMap.dtype.fields.items():
                aux = self._sparseMap[key].astype(np.float64)
                aux[self._sparseMap[self._primary] == self._sentinel] = np.nan
                aux = aux.reshape((npop_pix+1, (nside_out//self._nsideCoverage)**2, -1))
                # Perform the reduction operation (check utils.reduce_array)
                aux = reduce_array(aux, reduction=reduction)
                # Transform back to UNSEEN
                aux[np.isnan(aux)] = hp.UNSEEN
                newsparseMap[key] = aux

        # Work with regular ndarray
        else:
            if issubclass(self._sparseMap.dtype.type, np.integer):
                aux_dtype = np.float64
            else:
                aux_dtype = self._sparseMap.dtype

            aux = self._sparseMap.astype(aux_dtype)
            aux[self._sparseMap == self._sentinel] = np.nan
            aux = aux.reshape((npop_pix+1, (nside_out//self._nsideCoverage)**2, -1))
            aux = reduce_array(aux, reduction=reduction)
            # NaN are converted to UNSEEN
            aux[np.isnan(aux)] = hp.UNSEEN
            newsparseMap = aux

        # The coverage index map is now offset, we have to build a new one
        newIndexMap = np.zeros(hp.nside2npix(self._nsideCoverage), dtype=np.int64)
        newIndexMap[self.coverageMask] = np.arange(1, npop_pix + 1) * nFinePerCov
        newIndexMap[:] -= np.arange(hp.nside2npix(self._nsideCoverage), dtype=np.int64) * nFinePerCov
        return HealSparseMap(covIndexMap=newIndexMap, sparseMap=newsparseMap, nsideCoverage=self._nsideCoverage,
                             nsideSparse=nside_out, primary=self._primary, sentinel=hp.UNSEEN)

    def applyMask(self, maskMap, maskBits=None, inPlace=True):
        """
        Apply an integer mask to the map.  All pixels in the integer
        mask that have any bits in maskBits set will be zeroed in the
        output map.  The default is that this operation will be done
        in place, but it may be set to return a copy with a masked map.

        Parameters
        ----------
        maskMap: `HealSparseMap`
           Integer mask to apply to the map.
        maskBits: `int`, optional
           Bits to be treated as bad in the maskMap.
           Default is None (all non-zero pixels are masked)
        inPlace: `bool`, optional
           Apply operation in place.  Default is True

        Returns
        -------
        maskedMap: `HealSparseMap`
           self if inPlace is True, a new copy otherwise
        """

        # Check that the maskMap is an integer map (and not a recArray)
        if not maskMap.isIntegerMap:
            raise RuntimeError("Can only apply a maskMap that is an integer map.")

        # operate on this map validPixels
        validPixels = self.validPixels

        if maskBits is None:
            badPixels, = np.where(maskMap.getValuePixel(validPixels) > 0)
        else:
            badPixels, = np.where((maskMap.getValuePixel(validPixels) & maskBits) > 0)

        if inPlace:
            newMap = self
        else:
            newMap = HealSparseMap(covIndexMap=self._covIndexMap.copy(),
                                   sparseMap=self._sparseMap.copy(),
                                   nsideSparse=self._nsideSparse,
                                   primary=self._primary,
                                   sentinel=self._sentinel)

        newValues = np.zeros(badPixels.size,
                             dtype=newMap._sparseMap.dtype)
        if self.isRecArray:
            newValues[newMap._primary] = newMap._sentinel
        else:
            newValues[:] = newMap._sentinel

        newMap.updateValues(validPixels[badPixels], newValues)

        return newMap

    def __getitem__(self, key):
        """
        Get a single healpix map out of a recarray map, using the default sentinel
        values.
        """

        if not self._isRecArray:
            raise TypeError("HealSparseMap is not a recarray map")

        return self.getSingle(key, sentinel=None)

    def getSingle(self, key, sentinel=None):
        """
        Get a single healpix map out of a recarray map, with the ability to
        override a sentinel value.

        Parameters
        ----------
        key: `str`
           Field for the recarray
        sentinel: `int` or `float` or None, optional
           Override the default sentinel value.  Default is None (use default)
        """

        if not self._isRecArray:
            raise TypeError("HealSparseMap is not a recarray map")

        if key == self._primary and sentinel is None:
            # This is easy, and no replacements need to happen
            return HealSparseMap(covIndexMap=self._covIndexMap, sparseMap=self._sparseMap[key], nsideSparse=self._nsideSparse, sentinel=self._sentinel)

        _sentinel = checkSentinel(self._sparseMap[key].dtype.type, sentinel)

        newSparseMap = np.zeros_like(self._sparseMap[key]) + _sentinel

        validIndices = (self._sparseMap[self._primary] > self._sentinel)
        newSparseMap[validIndices] = self._sparseMap[key][validIndices]

        return HealSparseMap(covIndexMap=self._covIndexMap, sparseMap=newSparseMap, nsideSparse=self._nsideSparse, sentinel=_sentinel)

    def __add__(self, other):
        """
        Add a constant.

        Cannot be used with recarray maps.
        """

        return self._applyOperation(other, np.add)

    def __iadd__(self, other):
        """
        Add a constant, in place.

        Cannot be used with recarray maps.
        """

        return self._applyOperation(other, np.add, inPlace=True)

    def __sub__(self, other):
        """
        Subtract a constant.

        Cannot be used with recarray maps.
        """

        return self._applyOperation(other, np.subtract)

    def __isub__(self, other):
        """
        Subtract a constant, in place.

        Cannot be used with recarray maps.
        """

        return self._applyOperation(other, np.subtract, inPlace=True)

    def __mul__(self, other):
        """
        Multiply a constant.

        Cannot be used with recarray maps.
        """

        return self._applyOperation(other, np.multiply)

    def __imul__(self, other):
        """
        Multiply a constant, in place.

        Cannot be used with recarray maps.
        """

        return self._applyOperation(other, np.multiply, inPlace=True)

    def __truediv__(self, other):
        """
        Divide a constant.

        Cannot be used with recarray maps.
        """

        return self._applyOperation(other, np.divide)

    def __itruediv__(self, other):
        """
        Divide a constant, in place.

        Cannot be used with recarray maps.
        """

        return self._applyOperation(other, np.divide, inPlace=True)

    def __pow__(self, other):
        """
        Raise the map to a power.

        Cannot be used with recarray maps.
        """

        return self._applyOperation(other, np.power)

    def __ipow__(self, other):
        """
        Divide a constant, in place.

        Cannot be used with recarray maps.
        """

        return self._applyOperation(other, np.power, inPlace=True)


    def __and__(self, other):
        """
        Perform a bitwise and with a constant.

        Cannot be used with recarray maps.
        """

        return self._applyOperation(other, np.bitwise_and, intOnly=True)

    def __iand__(self, other):
        """
        Perform a bitwise and with a constant, in place.

        Cannot be used with recarray maps.
        """

        return self._applyOperation(other, np.bitwise_and, intOnly=True, inPlace=True)

    def __xor__(self, other):
        """
        Perform a bitwise xor with a constant.

        Cannot be used with recarray maps.
        """

        return self._applyOperation(other, np.bitwise_xor, intOnly=True)

    def __ixor__(self, other):
        """
        Perform a bitwise xor with a constant, in place.

        Cannot be used with recarray maps.
        """

        return self._applyOperation(other, np.bitwise_xor, intOnly=True, inPlace=True)

    def __or__(self, other):
        """
        Perform a bitwise or with a constant.

        Cannot be used with recarray maps.
        """

        return self._applyOperation(other, np.bitwise_or, intOnly=True)

    def __ior__(self, other):
        """
        Perform a bitwise or with a constant, in place.

        Cannot be used with recarray maps.
        """

        return self._applyOperation(other, np.bitwise_or, intOnly=True, inPlace=True)

    def _applyOperation(self, other, func, intOnly=False, inPlace=False):
        """
        Apply a generic arithmetic function.

        Cannot be used with recarray maps.

        Parameters
        ----------
        other: `int` or `float` (or numpy equivalents)
           The other item to perform the operator on.
        func: `np.ufunc`
           The numpy universal function to apply.
        intOnly: `bool`, optional
           Only accept integer types.  Default is False.
        inPlace: `bool`, optional
           Perform operation in-place.  Default is False.

        Returns
        -------
        result: `HealSparseMap`
           Resulting map
        """

        name = func.__str__()

        if self._isRecArray:
            raise NotImplementedError("Cannot use %s with recarray maps" % (name))
        if intOnly:
            if not issubclass(self._sparseMap.dtype.type, np.integer):
                raise NotImplementedError("Can only apply %s to integer maps" % (name))

        otherInt = False
        otherFloat = False
        if (issubclass(other.__class__, int) or
            issubclass(other.__class__, np.integer)):
            otherInt = True
        elif (issubclass(other.__class__, float) or
              issubclass(other.__class__, np.floating)):
            otherFloat = True

        if not otherInt and not otherFloat:
            raise NotImplementedError("Can only use a constant with the %s operation" % (name))

        if not otherInt and intOnly:
            raise NotImplementedError("Can only use an integer constant with the %s operation" % (name))

        validSparsePixels = (self._sparseMap > self._sentinel)
        if inPlace:
            func(self._sparseMap, other, out=self._sparseMap, where=validSparsePixels)
            return self
        else:
            combinedSparseMap = self._sparseMap.copy()
            func(combinedSparseMap, other, out=combinedSparseMap, where=validSparsePixels)
            return HealSparseMap(covIndexMap=self._covIndexMap, sparseMap=combinedSparseMap, nsideSparse=self._nsideSparse, sentinel=self._sentinel)

    def __copy__(self):
        return HealSparseMap(covIndexMap=self._covIndexMap.copy(), sparseMap=self._sparseMap.copy(), nsideSparse=self._nsideSparse, sentinel=self._sentinel, primary=self._primary)

    def copy(self):
        return self.__copy__()

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        descr = 'HealSparseMap: nsideCoverage = %d, nsideSparse = %d' % (self._nsideCoverage, self._nsideSparse)
        if self._isRecArray:
            descr += ', record array type.\n'
            descr += self._sparseMap.dtype.descr.__str__()
        else:
            descr += ', ' + self._sparseMap.dtype.name
        return descr
